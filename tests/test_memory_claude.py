"""Synthetic export blocks: prevent reasoning/tool traces becoming evidence."""
import unittest
from pipeline.memory_center.claude import messages, visible_blocks
from pipeline.memory_center.bulk import _segments


class ClaudeParserTest(unittest.TestCase):
    def test_structured_visible_text_excludes_thinking_and_tools(self):
        raw={'uuid':'synthetic','sender':'assistant','text':'hidden reasoning and tool output and answer',
             'content':[{'type':'thinking','thinking':'hidden reasoning'},
                        {'type':'tool_result','text':'tool output'},
                        {'type':'text','text':'visible answer'}]}
        output=list(messages({'name':'Synthetic export','chat_messages':[raw]}))
        self.assertEqual(output[0]['text'],'visible answer')
        self.assertEqual(output[0]['id'],'synthetic#t2p0')
        self.assertEqual(output[0]['role'],'assistant')

    def test_no_fallback_from_empty_or_malformed_structured_content(self):
        for content in [[], None, {}, [{'type':'thinking','thinking':'not testimony'}]]:
            self.assertEqual(list(visible_blocks({'text':'flattened unsafe','content':content})),[])
        self.assertEqual(list(visible_blocks({'text':'legacy visible'})),[('legacy','legacy visible')])

    def test_content_blocks_have_stable_lossless_separate_locators(self):
        body='合成正文'*4000
        c={'name':'Synthetic','chat_messages':[{'uuid':'m','sender':'human','content':[
            {'type':'text','text':body},{'type':'text','text':'second block'}]}]}
        segments=list(_segments(c));parts=[m for segment in segments for m in segment]
        self.assertEqual(''.join(m['text'] for m in parts if '#t0p' in m['id']),body)
        self.assertEqual(len(set(m['id'] for m in parts)),len(parts))
        self.assertEqual(parts[-1]['id'],'m#t1p0')
        self.assertTrue(all(m['role']=='user' for m in parts))

    def test_escaped_export_text_splits_without_loss(self):
        from pipeline.memory_center.core import encoded
        body='\\\n\t'*10000
        parts=[message for group in _segments({'uuid':'synthetic','chat_messages':[
            {'uuid':'m','sender':'human','content':[{'type':'text','text':body}]}]}) for message in group]
        self.assertEqual(''.join(m['text'] for m in parts),body)
        self.assertTrue(all(len(encoded([m]))<=24000 for m in parts))


if __name__ == '__main__': unittest.main()
