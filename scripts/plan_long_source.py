#!/usr/bin/env python3
"""Write a private offline archive plan. Never imports or invokes a model."""
import argparse
import json
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from pipeline.memory_center.long_source_plan import plan_long_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        source = Path(args.input)
        destination = Path(args.output).resolve()
        if destination == REPO or REPO in destination.parents or source.stat().st_size > 5_000_000:
            raise ValueError('private_bounded_paths_required')
        data = json.loads(source.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or set(data) - {
            'source_key', 'scope', 'source_type', 'source_metadata', 'messages'
        }:
            raise ValueError('invalid_envelope')
        plan = plan_long_source(**data)
        body = json.dumps(plan, ensure_ascii=False, indent=2).encode('utf-8')
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(body)
        print(json.dumps({'planner_version': plan['planner_version'],
                          'segment_count': len(plan['segments']), 'source_characters': plan['source_characters'],
                          'model_calls': 0, 'quality_approved': False}))
        return 0
    except Exception:
        print('Long source planning failed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
