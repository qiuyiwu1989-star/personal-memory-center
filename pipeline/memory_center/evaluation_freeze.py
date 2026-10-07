"""Offline trial binding checks. No model, writeback or quality approval."""
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,
                                    separators=(',',':'),allow_nan=False).encode()).hexdigest()


def review_binding(run, contract):
    """Bind a review to the exact output and frozen source/configuration contract."""
    output={k:run.get(k) for k in
        ('case_id','source_sha256','method_version','prompt_sha256','model_profile_sha256','claims')}
    # Preserve historical receipt hashes while binding actual bounded inputs
    # for new trials. Same source/method can produce different context windows.
    output.update({k:run[k] for k in ('request_fingerprint','scope_contract_sha256') if k in run})
    return digest({'contract':contract,'output':output})


def trial_readiness(manifest, runs):
    """A declared independent review is not independently proven by this function."""
    cases=manifest.get('cases')
    if not isinstance(cases,list) or not cases:raise ValueError('Nonempty frozen cases required')
    required=('case_id','source_sha256','method_version','prompt_sha256','model_profile_sha256')
    contracts={}
    for case in cases:
        if not isinstance(case,dict) or any(not isinstance(case.get(k),str) or not case[k] for k in required):
            raise ValueError('Complete frozen case binding required')
        if case['case_id'] in contracts:raise ValueError('Duplicate frozen case')
        for k in ('source_sha256','prompt_sha256','model_profile_sha256'):
            if len(case[k])!=64 or any(c not in '0123456789abcdef' for c in case[k]):raise ValueError('Invalid digest')
        if case.get('expected_output') not in (None,'empty','nonempty'):
            raise ValueError('Invalid expected output contract')
        if case.get('expected_output')=='empty' and case.get('requires_nonempty_claims') is not False:
            raise ValueError('Empty expectation requires an explicit negative case')
        for k in ('request_fingerprint','scope_contract_sha256'):
            if k in case and (not isinstance(case[k],str) or len(case[k])!=64
                              or any(c not in '0123456789abcdef' for c in case[k])):
                raise ValueError('Invalid bounded input digest')
        contracts[case['case_id']]=case
    cap=manifest.get('token_limit')
    if type(cap) is not int or cap<=0:raise ValueError('Positive finite trial limit required')
    grouped={};charged=0;unknown=0;reasons=[]
    for run in runs:
        if not isinstance(run,dict):raise ValueError('Invalid trial run')
        grouped.setdefault(run.get('case_id'),[]).append(run)
        usage=run.get('usage') or {}
        if not isinstance(usage,dict):raise ValueError('Invalid usage receipt')
        count=usage.get('total_tokens');reservation=run.get('reserved_tokens')
        if type(count) is int and count>=0:charged+=count
        else:
            unknown+=1
            if type(reservation) is not int or reservation<1:reasons.append('unknown_usage_without_reservation')
            else:charged+=reservation
    if charged>cap:reasons.append('trial_budget_exceeded')
    if unknown:reasons.append('unknown_usage_requires_resolution')
    if manifest.get('holdout_independence')!='verified':reasons.append('independence_not_verified')
    dimensions=('semantic_support','speaker_attribution','time_handling','scope_handling','durable_value','coverage')
    for cid,contract in contracts.items():
        items=grouped.get(cid,[])
        if len(items)!=1:reasons.append(cid+':missing_or_duplicate_run');continue
        run=items[0]
        if any(run.get(k)!=contract[k] for k in required):reasons.append(cid+':frozen_input_mismatch');continue
        bounded=(contract.get('input_kind')=='bounded_source_request'
                 or contract['method_version']=='2026-10-04.22'
                 or 'request_fingerprint' in contract or 'request_fingerprint' in run
                 or 'scope_contract_sha256' in contract or 'scope_contract_sha256' in run)
        if bounded and not contract.get('request_fingerprint'):
            reasons.append(cid+':unfrozen_bounded_input');continue
        if bounded and (run.get('request_fingerprint')!=contract['request_fingerprint']
                or run.get('scope_contract_sha256')!=contract.get('scope_contract_sha256')):
            reasons.append(cid+':frozen_request_mismatch');continue
        claims=run.get('claims')
        if not isinstance(claims,list) or any(not isinstance(c,dict) for c in claims):
            reasons.append(cid+':invalid_output');continue
        review=run.get('review') or {}
        if not isinstance(review,dict) or review.get('binding_sha256')!=review_binding(run,contract):
            reasons.append(cid+':stale_or_missing_review');continue
        if any(review.get(k)!='pass' for k in dimensions):reasons.append(cid+':review_incomplete_or_failed')
        # Positive cases must not pass by returning nothing. Review still judges semantics.
        if contract.get('requires_nonempty_claims') is not False and not claims:
            reasons.append(cid+':empty_positive_output')
        if contract.get('expected_output')=='nonempty' and not claims:
            reasons.append(cid+':empty_positive_output')
        if contract.get('expected_output')=='empty' and claims:
            reasons.append(cid+':nonempty_negative_output')
    if set(grouped)-set(contracts):reasons.append('unexpected_cases')
    return {'manifest_sha256':digest(manifest),'charged_or_reserved_tokens':charged,
            'unknown_usage_attempts':unknown,'blocking_reasons':sorted(set(reasons)),
            'ready_for_quality_decision':not reasons,'quality_approved':False,
            'production_dispatch_enabled':False,'model_calls':0,
            'independence_status_is_declaration':True}
