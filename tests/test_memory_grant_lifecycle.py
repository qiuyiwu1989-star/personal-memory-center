"""Synthetic private-file grants: expiry and revocation apply on next reload."""
import json,tempfile,time,unittest
from pathlib import Path
from pipeline.memory_center.web import load_grants
from pipeline.memory_center.core import Invalid

class GrantLifecycleTests(unittest.TestCase):
    def load(self,rows):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'synthetic-grants.json';path.write_text(json.dumps(rows))
            return load_grants(path)
    def grant(self,**fields):
        return dict(token_sha256='synthetic-not-a-token',id='synthetic-reader',owner='synthetic-owner',scopes=['synthetic'],actions=['read'],**fields)
    def test_existing_and_future_grants_remain_active(self):
        self.assertEqual(len(self.load([self.grant(),self.grant(expires_at=time.time()+3600)])),2)
    def test_expired_disabled_and_empty_fail_closed(self):
        self.assertEqual(self.load([self.grant(expires_at=time.time()-1),self.grant(enabled=False)]),[])
        self.assertEqual(self.load([]),[])
    def test_malformed_validity_is_rejected(self):
        for fields in ({'expires_at':True},{'expires_at':'tomorrow'},{'expires_at':float('nan')},{'enabled':'false'}):
            with self.assertRaises(Invalid):self.load([self.grant(**fields)])

if __name__=='__main__':unittest.main()
