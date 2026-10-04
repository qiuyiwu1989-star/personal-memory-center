#!/usr/bin/env python3
"""Save a source-complete private review packet, without model or network calls."""
import argparse
import json
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from pipeline.memory_center.scope_review import prepare_scope_review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        source = Path(args.input)
        destination = Path(args.output).resolve()
        # Original private text must not land in the public repository. Existing
        # packets are immutable; a later review creates a separate revision.
        if destination == REPO or REPO in destination.parents:
            raise ValueError('private_output_required')
        if source.stat().st_size > 2_000_000:
            raise ValueError('input_too_large')
        data = json.loads(source.read_text())
        if (not isinstance(data, dict) or set(data) - {
            'source_type', 'messages', 'processing_method_version', 'source_metadata'
        } or not isinstance(data.get('processing_method_version'), str)):
            raise ValueError('invalid_input')
        packet = prepare_scope_review(data['source_type'], data['messages'],
            version=data['processing_method_version'], source_metadata=data.get('source_metadata'))
        body = json.dumps(packet, ensure_ascii=False, indent=2).encode()
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(body)
        print(json.dumps({'packet_version': packet['packet_version'],
                          'review_target_count': len(packet['review_targets']),
                          'model_calls': 0, 'quality_approved': False}))
        return 0
    except Exception:
        # No input paths, source details or credential-bearing errors in logs.
        print('Scope review preparation failed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
