import json
import tempfile
import unittest
from pathlib import Path
from pipeline.memory_center.archive import build

class ArchiveTest(unittest.TestCase):
    def test_archive_includes_all_files_and_content_hashes(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'source';source.mkdir();(source/'a.txt').write_text('你好')
            (source/'sub').mkdir();(source/'sub'/'b.bin').write_bytes(bytes(range(256)))
            result=build(source,Path(d)/'out')
            manifest=json.loads((Path(result['directory'])/'manifest.json').read_text())
            self.assertEqual(result['file_count'],2)
            self.assertEqual(result['source_bytes'],262)
            self.assertEqual({x['path'] for x in manifest['files']},{'a.txt','sub/b.bin'})
            self.assertEqual(build(source,Path(d)/'out')['batch_id'],result['batch_id'])
    def test_reject_nested_output_and_links(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'source';source.mkdir();(source/'a').write_text('x')
            with self.assertRaises(ValueError):build(source,source/'out')
            (source/'link').symlink_to(source/'a')
            with self.assertRaises(ValueError):build(source,Path(d)/'out')
