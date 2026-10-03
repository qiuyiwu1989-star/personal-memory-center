"""Narrow omission rejection; never add qualifications or establish validity."""
import re

GUARD_VERSION = 'shared-rule-time-v1'


def qualification_problem(quote, statement, kind):
    """Check only an explicit common-time normative block in Chinese.

    Mixed speakers, quotations, lists, competing dates or scope transitions stay
    for semantic review. A no-problem result is NOT entailment/quality approval.
    Exact-source preservation is intentionally conservative; no auto-repair.
    """
    if kind not in ('claim', 'decision'):
        return None
    if re.search(r'[“”「」"\n]|说|表示|建议|希望|计划|打算|另外|但是|仅|只限|如果|除非|\d{4}[-年/]|次日起|明天|下周|之前|之后', quote):
        return None
    match = re.fullmatch(
        r'(?:我决定[:：])?从现在起[，,](?:以下全部规则|这两条要求|所有这些要求)'
        r'长期适用[，,]直到我明确更改[:：](?P<rules>[^。！？!?\n]+)[。.]?\s*', quote)
    if not match or not re.search(r'必须|禁止|不能|不得|要求', match['rules']):
        return None
    if re.search(r'生效|有效期|期限|[年月周日天]|后才|但|例外|除|从|起|长期|直到|直至', match['rules']):
        return None
    # Only the common block's own normative claims are checked. No propagation
    # to other kinds, and neither role nor approval is inferred by this helper.
    groups = (
        ('生效起点', ('从现在起', '从此刻起', '自现在起')),
        ('持续时间', ('长期适用', '长期有效', '长期')),
        ('结束条件', ('直到我明确更改', '直到用户明确更改', '直至用户明确更改', '直至我明确更改')),
    )
    for label, alternatives in groups:
        if any(re.search(r'(?:不是|并非|并不|不再|不|没有|无需|非)[\s（(【\[]*' + re.escape(value), statement) for value in alternatives):
            return '拆分后的共同规则否定了明确' + label + '，需复核'
        if not any(value in statement for value in alternatives):
            return '拆分后的共同规则遗漏明确' + label + '，需保留来源限定或复核'
    return None
