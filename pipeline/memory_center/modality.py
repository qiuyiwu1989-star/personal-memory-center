"""Conservative evidence boundaries and modality guards, never truth verification."""
import re

WISH = re.compile(r'希望|想要|考虑|期望|愿望|\b(?:wish|would like|hope|consider)\b', re.I)
PLAN = re.compile(r'计划|打算|准备|拟(?:于|在|采用)|\b(?:plan|intend)\b', re.I)
CONDITION = re.compile(r'如果|只要|只有|除非|倘若|假如|若(?:能|是|有|通过)|前提|在.{1,40}的情况下|通过后|\b(?:if|unless|provided that)\b', re.I)
ASSERTED = re.compile(r'已(?:经)?(?:决定|确定|完成|实现|部署|采用)|确定采用|正式采用|\b(?:completed|implemented|decided|deployed)\b', re.I)
LIST = re.compile(r'(?:^|\n)\s*(?:[-*•]|\d+[.、)]|[一二三四五六七八九十]+[、.])\s*')
PERMISSION = re.compile(r'可以|可选|允许|\b(?:may|can|optional|permitted)\b', re.I)
OBLIGATION = re.compile(r'要求|必须|应当|禁止|不得|不允许|不可以|不能|不应|决定|\b(?:must|required|requires?|mandatory|shall|forbidden|prohibited|decided)\b', re.I)


def _strong_statement(text):
    """Ignore plainly negated obligations, e.g. 不要求 and not required.

    This is deliberately narrow: ambiguous mixed or double-negated statements
    stay for semantic review rather than being called safe by this helper.
    """
    # Negation can govern a later modal phrase (不要求它必须...). Abstain
    # on that entire statement instead of pretending to resolve its scope.
    if re.search(r'(?:不|没有|无需|无须|并非|不是)\s*(?:要求|必须|应当|禁止)|\b(?:not|no)\s+(?:required|mandatory|prohibited)',text,re.I):
        return False
    for match in OBLIGATION.finditer(text):
        prefix=text[max(0,match.start()-20):match.start()]
        if re.search(r'(?:不|没有|无需|无须|并非|不是|not\s|no\s)\s*$',prefix,re.I):
            continue
        return True
    return False


def evidence_ranges(text):
    """Yield contiguous, lossless offsets; retain conditional/list context.

    Conservative segmentation is not full syntactic parsing. Ambiguous long
    passages remain intact for the model, never reduced to unsupported fragments.
    """
    if CONDITION.search(text) or LIST.search(text) or (':' in text or '：' in text) and '\n' in text:
        return [(0, len(text))] if text else []
    cuts = []
    stack = []
    pairs = {'(': ')', '（': '）', '[': ']', '【': '】', '“': '”', '「': '」', '《': '》'}
    for index, char in enumerate(text):
        if char in pairs:
            stack.append(pairs[char])
        elif stack and char == stack[-1]:
            stack.pop()
        elif not stack:
            suffix = text[index + 1:]
            boundary = char in '。！？!?；;'
            # A comma is safe only with a visibly new attributed intention;
            # never split ordinary coordinated constraints or a name list.
            boundary |= char in '，,' and bool(re.match(r'\s*(?:但|而)?(?:我|我们)(?:希望|想要|计划|打算|考虑)', suffix))
            # Pronouns and omitted subjects retain their antecedent context.
            independent = re.match(r'\s*(?:但|而)?(?:我(?:们)?|本项目|该项目|系统|项目|用户|[A-Za-z][A-Za-z0-9_-]*\s)', suffix)
            if boundary and suffix.strip() and independent:
                cuts.append(index + 1)
    positions = [0, *cuts, len(text)]
    return [(start, end) for start, end in zip(positions, positions[1:]) if start < end]


def evidence_modality(text):
    if CONDITION.search(text):
        return 'conditional'
    intention = WISH.search(text) or PLAN.search(text)
    if intention and ASSERTED.search(text):
        return 'mixed'
    if WISH.search(text):
        return 'wish'
    if PLAN.search(text):
        return 'plan'
    return 'stated'


def modality_problem(quote, statement, kind):
    """Return a high precision rejection reason, not a semantic entailment score.

    A mixed/conditional source can support named facts. Only obvious unsupported
    modal promotion is rejected; all other claims still need quality evaluation.
    """
    mode = evidence_modality(quote)
    # Only an entirely permissive source qualifies. Any obligation/decision
    # marker in a mixed source makes this lexical guard abstain; it must not
    # erase a genuine mandatory fact next to an optional one.
    if PERMISSION.search(quote) and not OBLIGATION.search(quote) and _strong_statement(statement):
        return '许可或可选项证据不能增强为要求、必须或禁止'
    if mode in ('wish', 'plan'):
        # A named fact inside an unsplittable mixed passage is not automatically
        # a wish. Strong completion still requires explicit source support.
        if ASSERTED.search(statement) and not ASSERTED.search(quote):
            return '意愿或计划证据不能升格为已决定或已完成'
        if kind in ('decision', 'event') and not ASSERTED.search(quote):
            return '意愿或计划证据不支持决定或已发生事件类型'
    if mode == 'conditional' and (ASSERTED.search(statement) or WISH.search(statement) or PLAN.search(statement)) and not CONDITION.search(statement) and not ASSERTED.search(quote):
        return '条件性安排不能省略成立条件'
    for verb in ('希望', '想要', '计划', '打算'):
        if re.search(r'(?:不|并不|没有)'+verb, quote) and verb in statement and not re.search(r'(?:不|并不|没有)'+verb, statement):
            return '否定意愿不能改写为肯定意愿'
    return None
