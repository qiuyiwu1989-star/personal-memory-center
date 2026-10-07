#!/usr/bin/env python3
"""Build a private offline long-source review packet, without model or writes to a store."""
import argparse
import json
import os
from pathlib import Path
import sys
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
from pipeline.memory_center.long_source_plan import plan_long_source
from pipeline.memory_center.scope_review import prepare_long_source_review


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--method-version',default='2026-10-04.22',choices=['2026-10-03.21','2026-10-04.22'])
    args=parser.parse_args()
    try:
        source=Path(args.input); destination=Path(args.output).resolve()
        if destination==REPO or REPO in destination.parents or source.stat().st_size>5_000_000:
            raise ValueError('private_bounded_paths_required')
        data=json.loads(source.read_text(encoding='utf-8'))
        # Also accepts development receipts, while verifying their original
        # envelope against the existing plan rather than trusting ledger counts.
        envelope=data.get('original_envelope',data)
        plan=data.get('plan') or data.get('archive_plan')
        if plan is None:plan=plan_long_source(**envelope)
        packet=prepare_long_source_review(envelope,plan,version=args.method_version)
        body=json.dumps(packet,ensure_ascii=False,indent=2).encode()
        fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb')as stream:stream.write(body)
        print(json.dumps({k:packet[k]for k in ('packet_version','method_version','archive_characters',
            'extraction_evidence_characters','unreviewed_segments','model_calls','quality_approved')}))
        return 0
    except Exception:
        print('Long source review failed.',file=sys.stderr)
        return 1
if __name__=='__main__':raise SystemExit(main())
