import unittest
from pipeline.memory_center.core import encoded,Invalid
from pipeline.memory_center.reading import search_page

class SearchBudgetTest(unittest.TestCase):
    def test_serialized_response_envelope_and_escaping_are_bounded(self):
        row={'id':'r','statement':'\\"😊'*180,'subject':'synthetic','status':'source_reported','source_id':'s','message_id':'m','source_date':None,'revision':1,'governance':{}}
        result=search_page({'records':[row],'total':1},500)
        self.assertLessEqual(len(encoded(result)),500);self.assertEqual(result['records'],[]);self.assertTrue(result['truncated'])
        row['statement']='合成候选'
        result=search_page({'records':[row],'total':1},500)
        self.assertEqual(len(result['records']),1);self.assertFalse(result['truncated'])
        self.assertLessEqual(len(encoded(result)),500)
        with self.assertRaises(Invalid):search_page({'records':[],'total':0},True)
