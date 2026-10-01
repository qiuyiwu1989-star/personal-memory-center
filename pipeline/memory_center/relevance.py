"""Offline, closed-corpus relevance scoring. Labels are judgments, not truth approval."""
import hashlib
import json


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def score(contract, report, k=5):
    if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= 100:
        raise ValueError('k must be 1..100')
    if contract.get('annotation_status') != 'agent_review_provisional':
        raise ValueError('Explicit provisional annotation status required')
    for field in ('input_sha256', 'results_sha256'):
        if not contract.get(field) or report.get(field) != contract[field]:
            raise ValueError('Corpus receipt mismatch: ' + field)
    corpus = set(contract['corpus_record_ids'])
    if len(corpus) != len(contract['corpus_record_ids']):
        raise ValueError('Duplicate corpus identities')
    tasks = {task['task_id']: task for task in contract['tasks']}
    if len(tasks) != len(contract['tasks']):
        raise ValueError('Duplicate contract task')
    actual = {task['task_id']: task for task in report['tasks']}
    if len(actual) != len(report['tasks']) or set(actual) != set(tasks):
        raise ValueError('Task set mismatch')
    rows = []
    for task_id, task in tasks.items():
        found = actual[task_id]
        if task['query'] != found['query']:
            raise ValueError('Query changed')
        labels = task['labels']
        if set(labels) != corpus or any(v['grade'] not in (0, 1, 2) for v in labels.values()):
            raise ValueError('Every corpus item requires a valid grade')
        ids = found['candidate_record_ids']
        if len(ids) != len(set(ids)) or not set(ids) <= corpus:
            raise ValueError('Unknown or duplicate returned identity')
        returned = ids[:k]
        positives = {key for key, value in labels.items() if value['grade'] == 2}
        hits = [key for key in returned if key in positives]
        # Fixed-k precision penalizes unfilled slots on positive tasks. Empty-target
        # cases are evaluated by false returns, never perfect recall or precision.
        rows.append({'task_id': task_id, 'target_count': len(positives),
                     'returned_at_k': len(returned), 'relevant_at_k': len(hits),
                     'precision_at_k': len(hits)/k if positives else None,
                     'recall_at_k': len(hits)/len(positives) if positives else None,
                     'mrr_at_k': next((1/(i+1) for i, key in enumerate(returned)
                                       if key in positives), 0) if positives else None,
                     'false_returns_at_k': sum(labels[key]['grade'] == 0 for key in returned),
                     'support_only_at_k': sum(labels[key]['grade'] == 1 for key in returned),
                     'negative_case_correct_abstention': not returned if not positives else None})
    positive_rows = [row for row in rows if row['target_count']]
    negative_rows = [row for row in rows if not row['target_count']]
    return {'annotation_status': 'agent_review_provisional', 'quality_gate_passed': False,
            'contract_sha256': fingerprint(contract), 'k': k, 'tasks': rows,
            'summary': {'tasks': len(rows), 'positive_tasks': len(positive_rows),
                        'negative_tasks': len(negative_rows),
                        **{metric: sum(row[metric] for row in positive_rows)/len(positive_rows)
                           if positive_rows else None for metric in
                           ('precision_at_k', 'recall_at_k', 'mrr_at_k')},
                        'negative_correct_abstentions': sum(row['negative_case_correct_abstention']
                                                            for row in negative_rows),
                        'false_returns_at_k': sum(row['false_returns_at_k'] for row in rows)},
            'model_calls': 0, 'actual_model_tokens': 0,
            'limitations': ['Agent provisional labels, not independent human gold or owner confirmation.',
                            'Closed extracted corpus: recall excludes missed extraction and archived documents.',
                            'Candidate relevance does not establish current validity or usable-context quality.']}
