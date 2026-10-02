"""Shared judgment metadata contract; unknown attribution remains unknown.

This contract validates structure and current validity, not semantic truth.
It never resolves names, assumes a holder, or infers explicit confirmation.
"""
import datetime
from .core import Invalid

FIELDS = frozenset(('holder', 'subject_id', 'as_of', 'valid_until', 'state', 'priority', 'note'))
STATES = frozenset(('candidate', 'verified', 'historical', 'rejected'))


def normalize(body):
    """Return canonical governance metadata, without changing trust state."""
    if not isinstance(body, dict) or set(body) - FIELDS:
        raise Invalid('治理字段无效')
    state = body.get('state', 'candidate')
    priority = body.get('priority', 'P3')
    if not isinstance(state, str) or state not in STATES:
        raise Invalid('治理状态无效')
    if not isinstance(priority, str) or priority not in ('P0', 'P1', 'P2', 'P3'):
        raise Invalid('优先级无效')
    values = {'state': state, 'priority': priority}
    for key in ('holder', 'subject_id', 'as_of', 'valid_until', 'note'):
        value = body.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > (1000 if key == 'note' else 160)):
            raise Invalid('治理字段无效')
        # Do not repair a date or resolve an identity implicitly.
        values[key] = value or ('' if key == 'note' else None)
    for key in ('as_of', 'valid_until'):
        if values[key]:
            try:
                if datetime.date.fromisoformat(values[key]).isoformat() != values[key]:
                    raise ValueError('noncanonical date')
            except ValueError:
                raise Invalid('有效日期需为 YYYY-MM-DD') from None
    if values['valid_until'] and values['as_of'] and values['valid_until'] < values['as_of']:
        raise Invalid('失效时间不能早于成立时间')
    if state == 'verified' and any(not values[key] for key in ('holder', 'subject_id', 'as_of')):
        raise Invalid('核实记忆需明确主张者、对象和成立日期；未知时保留候选')
    return values


def validate_verified(db, owner, scope, values, today=None):
    """Require scoped registered identities and a currently valid interval.

    valid_until is exclusive: on that date a judgment is no longer current.
    Future/historical metadata may be archived, but cannot be verified current.
    """
    if values['state'] != 'verified':
        return
    date = today or datetime.date.today().isoformat()
    if not values.get('as_of') or not values.get('holder') or not values.get('subject_id'):
        raise Invalid('核实记忆需明确主张者、对象和成立日期')
    if values['as_of'] > date or (values.get('valid_until') and values['valid_until'] <= date):
        raise Invalid('未来或已失效陈述不可标为当前有效 verified')
    from .entities import exists
    if any(not exists(db, owner, scope, values[key]) for key in ('holder', 'subject_id')):
        raise Invalid('核实前需登记主张者和对象的稳定实体 ID')
