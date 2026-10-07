#!/usr/bin/env python3
"""Build an offline, private purpose-limited request; never dispatch a model."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.memory_center.bounded_source_request import scoped_source_request
from pipeline.memory_center.long_source_plan import plan_long_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        target = args.output.resolve()
        if target == ROOT or ROOT in target.parents:
            raise ValueError('Private output required')
        if args.input.stat().st_size > 5_000_000 or args.selection.stat().st_size > 100_000:
            raise ValueError('Bounded inputs required')
        data = json.loads(args.input.read_text(encoding='utf-8'))
        envelope = data.get('original_envelope', data)
        archive = data.get('archive_plan') or data.get('plan') or plan_long_source(**envelope)
        selection = json.loads(args.selection.read_text(encoding='utf-8'))
        bundle = scoped_source_request(envelope, archive, selection, version='2026-10-04.22')
        receipt = dict(bundle=bundle, context_selection=selection,
            model_calls=0, production_writes=0, quality_approved=False,
            contains_private_source_text=True)
        # Parent location is chosen explicitly; do not create arbitrary trees.
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(receipt, stream, ensure_ascii=False, indent=2)
        print(json.dumps(dict(request_bytes=bundle['request_bytes'],
            context_complete=bundle['context_complete'], model_calls=0,
            production_writes=0, quality_approved=False)))
        return 0
    except Exception:
        print('Scoped request preparation failed; no model or production dispatch.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
