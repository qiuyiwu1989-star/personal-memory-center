"""Inventory by default. --enqueue explicitly queues summaries for model processing."""
import argparse
import json
import os
from pathlib import Path
from .core import Store, Invalid
from .web import load_grants


def summaries(data):
    for item in data.get('memory_files', []):
        yield 'claude:file:' + item['path'], item['content']
    if data.get('conversations_memory'):
        yield 'claude:global-summary', data['conversations_memory']
    for key, value in data.get('project_memories', {}).items():
        yield 'claude:project:' + key, value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export_json', type=Path)
    parser.add_argument('--enqueue', action='store_true')
    parser.add_argument('--scope', default='personal')
    args = parser.parse_args()
    data = json.loads(args.export_json.read_text())
    items = list(summaries(data))
    print(json.dumps({'summaries': len(items), 'characters': sum(len(text) for _, text in items),
                      'action': 'enqueue' if args.enqueue else 'inventory-only'}, ensure_ascii=False))
    if not args.enqueue:
        return
    # Explicit server-side import credentials, not a browser-provided owner id.
    store = Store(os.environ['QIU_MEMORY_DATA_DIR'])
    grants = load_grants(os.environ['QIU_MEMORY_GRANTS'])
    principal = next((g for g in grants if g['id'] == os.environ['QIU_MEMORY_IMPORT_PRINCIPAL']), None)
    if not principal:
        raise Invalid('导入主体未配置')
    queued = duplicate = 0
    for key, text in items:
        # Independent chunks preserve exact quotes; no cross-chunk synthesis in pilot.
        for part, start in enumerate(range(0, len(text), 18000)):
            result = store.ingest(principal, {'scope': args.scope, 'source_key': key + ':part:' + str(part),
                'source_type': 'imported_summary',
                'messages': [{'id': 'part-' + str(part), 'role': 'external', 'text': text[start:start+18000]}]})
            duplicate += result['duplicate']
            queued += not result['duplicate']
    print(json.dumps({'queued': queued, 'duplicate': duplicate}))


if __name__ == '__main__':
    main()
