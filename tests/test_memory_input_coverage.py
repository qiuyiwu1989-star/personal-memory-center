import copy
import unittest
from unittest.mock import patch
from pipeline.memory_center.input_coverage import audit_input_coverage
from pipeline.memory_center.core import Invalid

class InputCoverageTests(unittest.TestCase):
    def audit(self,messages,kind='document'):
        return audit_input_coverage(kind,messages,version='2026-10-03.21')
    def test_long_document_not_ready_even_with_full_spans(self):
        m=[{'id':'synthetic-long','role':'external','text':'合成会议记录。'*3000}]
        before=copy.deepcopy(m);r=self.audit(m)
        self.assertFalse(r['input_ready_without_segmentation'])
        self.assertTrue(r['full_evidence_coverage'])
        self.assertEqual(r['total_characters'],r['evidence_characters'])
        self.assertEqual(m,before)
        self.assertFalse(r['quality_approved'])
    def test_reference_route_exclusion_never_passes_coverage(self):
        text='你是合成角色。\n核心使命：工作流程。'+('合成原件内容。'*100)
        r=self.audit([{'id':'synthetic-template','role':'external','text':text}])
        self.assertFalse(r['full_evidence_coverage'])
        self.assertEqual(r['evidence_characters'],0)
        self.assertEqual(r['items'][0]['excluded_characters'],len(text))
        self.assertNotIn('text',r['items'][0])
    def test_assistant_archive_is_not_counted_as_personal_evidence(self):
        r=self.audit([{'id':'synthetic-a','role':'assistant','text':'合成助手建议。'}],'conversation')
        self.assertFalse(r['full_evidence_coverage'])
        self.assertEqual(r['items'][0]['route'],'assistant_reference')
    def test_wrong_locator_aborts(self):
        with patch('pipeline.memory_center.input_coverage.prepare_request',return_value=({}, {'bad':{'message_id':'synthetic','start':0,'end':3,'quote':'假文字'}},{'synthetic':'conversation'})):
            with self.assertRaises(Invalid):self.audit([{'id':'synthetic','role':'user','text':'合成文字'}])
    def test_duplicate_ids_and_invalid_role_rejected(self):
        m={'id':'synthetic','role':'user','text':'合成决定。'}
        with self.assertRaises(Invalid):self.audit([m,m])
        with self.assertRaises(Invalid):self.audit([dict(m,role='system')])
    def test_unicode_counts_not_bytes_or_tokens(self):
        r=self.audit([{'id':'synthetic','role':'user','text':'合成😊。'}])
        self.assertEqual(r['total_characters'],4)
        self.assertTrue(r['input_ready_without_segmentation'])
        self.assertEqual(r['model_calls'],0)
