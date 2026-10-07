#!/usr/bin/env python3
"""Check private frozen trial receipts offline; does not approve or dispatch."""
import argparse
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from pipeline.memory_center.evaluation_freeze import trial_readiness


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--runs',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();target=args.output.resolve()
    if target==ROOT or ROOT in target.parents:p.error('Receipts must remain outside public repository')
    result=trial_readiness(json.loads(args.manifest.read_text()),json.loads(args.runs.read_text()))
    target.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    # Avoid exposing private case identifiers or review content in logs.
    print(json.dumps({k:result[k] for k in ('ready_for_quality_decision','quality_approved',
         'production_dispatch_enabled','charged_or_reserved_tokens','unknown_usage_attempts','model_calls')}))
    return 0 if result['ready_for_quality_decision'] else 2
if __name__=='__main__':raise SystemExit(main())
