#!/usr/bin/env python3
"""Score fixed private relevance labels against a receipt-matched offline report."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.memory_center.relevance import score


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--k', default=5, type=int)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if output == repo or repo in output.parents:
        parser.error('Private scored report must stay outside public repository')
    result = score(json.loads(args.contract.read_text()), json.loads(args.report.read_text()), args.k)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as handle:
        output.chmod(0o600)
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps(result['summary'], ensure_ascii=False))

if __name__ == '__main__': main()
