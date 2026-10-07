"""Conservative evidence boundaries and modality guards, never truth verification."""
import re

WISH = re.compile(r'希望|想要|考虑|期望|愿望|\b(?:wish|would like|hope|consider)\b', re.I)
PLAN = re.compile(r'计划|打算|准备|拟(?:于|在|采用)|\b(?:plan|intend)\b', re.I)
CONDITION = re.compile(r'如果|只要|只有|除非|倘若|假如|若(?:能|是|有|通过)|前提|在.{1,40}的情况下|通过后|\b(?:if|unless|provided that)\b', re.I)
ASSERTED = re.compile(r'已(?:经)?(?:决定|确定|完成|实现|部署|采用)|确定采用|正式采用|\b(?:completed|implemented|decided|deployed)\b', re.I)
LIST = re.compile(r'(?:^|\n)\s*(?:[-*•]|\d+[.、)]|[一二三四五六七八九十]+[、.])\s*')
PERMISSION = re.compile(r'可以|可选|允许|\b(?:may|can|optional|permitted)\b', re.I)
OBLIGATION = re.compile(r'要求|必须|应当|禁止|不得|不允许|不可以|不能|不应|决定|\b(?:must|required|requires?|mandatory|shall|forbidden|prohibited|decided)\b', re.I)
GUARD_VERSION = 'permission-scope-v2'


def _permission_signal(text):
    """Artifact capability inside an explicit build request is not permission.

    Only a narrow capability construction is removed. Explicit optional/grant
    markers and remaining permission text still retain the existing guard.
    This is not a general modality parser or semantic quality approval.
    """
    if not re.search(r'允许|可选|可以选择|\b(?:may|optional|permitted)\b', text, re.I):
        text = re.sub(
            r'((?:做成|写成|制作|生成|构建|设计)[^。！？!?；;\n]{0,60})'
            r'可以(?=像|支持|实现|显示|切换|运行|翻页|播放|全屏|折叠|缩放)',
            r'\1能够', text)
    return bool(PERMISSION.search(text))


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
    if _permission_signal(quote) and not OBLIGATION.search(quote) and _strong_statement(statement):
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


SCOPED_GUARD_VERSION = 'condition-scope-v1'


def scoped_evidence_ranges(text):
    """v17 only: isolate an explicitly independent requirement at a hard boundary.

    This is deliberately not a general Chinese scope parser. A repeated subject,
    另外/总之, or a new object alone does not release a preceding condition.
    Independence must be declared with a concrete named project. Quoted words,
    lists, subordinate pronouns and ambiguous same-project recaps stay together.
    Original offsets and all preceding context remain available as separate spans.
    """
    if not CONDITION.search(text):
        return evidence_ranges(text)
    if LIST.search(text) or re.search(r'说|表示|写道|来信|访谈|转发|以下|下面|\b(?:said|says|letter|email|account from)\b',text,re.I):
        return [(0, len(text))] if text else []
    # Explicit, narrow author declaration; no heading/quotation/third-party text.
    independent = re.compile(
        r'\s*(?:另外，)?我对另一(?:个)?独立项目\s+[A-Za-z][A-Za-z0-9_-]*\s*的要求是[:：，,]')
    stack=[];cuts=[]
    pairs={'(':')','（':'）','[':']','【':'】','“':'”','「':'」','《':'》','"':'"'}
    for index,char in enumerate(text):
        if stack and char==stack[-1]:
            stack.pop()
        elif char in pairs:
            stack.append(pairs[char])
        elif not stack and char in '。！？!?':
            suffix=text[index+1:]
            if independent.match(suffix) and not CONDITION.search(suffix):
                cuts.append(index+1)
    if not cuts:
        return [(0,len(text))] if text else []
    positions=[0,*cuts,len(text)]
    return [(begin,end) for begin,end in zip(positions,positions[1:]) if begin<end]


SCOPED_V19_GUARD_VERSION = 'condition-scope-v2-explicit'


def scoped_evidence_ranges_v19(text):
    """Add only an explicit independence declaration before a conditional plan.

    This is not a scope parser. Adjacency, another subject or negated approval
    alone never establishes independence. The source must explicitly declare
    an independent wish AND deny approval, before a self-contained conditional
    first-person plan. Common scope, pronoun continuation, quotations and lists
    make this new rule abstain. v17/v18 boundaries remain unchanged.
    Offsets are Python string offsets, exactly as the existing source contract.
    """
    fallback = scoped_evidence_ranges(text)
    if not CONDITION.search(text):
        return fallback
    if LIST.search(text) or re.search(
        r'说|表示|认为|转述|引述|原话|写道|来信|访谈|转发|以下|下面|[“”「」《》"\[\]【】（）()]|'
        r"['`]|\b(?:said|says|letter|email|account from)\b", text, re.I):
        return [(0,len(text))] if text else []
    declaration = re.compile(
        r'(?:这项|该项|上述)?期望独立成立[，,；;]\s*(?:我)?(?:尚未|没有)批准(?:实施|执行)[。！？!?]\s*$')
    conditional_plan = re.compile(
        r'\s*(?:如果|倘若|假如)[^。！？!?\n]{1,80}[，,]\s*我(?:计划|打算|准备)')
    for boundary in re.finditer(r'[。！？!?]', text):
        cut = boundary.end()
        head, tail = text[:cut], text[cut:]
        if not (re.match(r'\s*我(?:希望|想要|期望|考虑)',head) and
                declaration.search(head) and conditional_plan.match(tail)):
            continue
        # A condition earlier in the wish or later in the plan can govern more
        # than this boundary. Multiple intentions and backward references also
        # need semantic review; keep all source context together.
        if CONDITION.search(head) or len(list(CONDITION.finditer(tail))) != 1:
            continue
        if len(list(WISH.finditer(head[:declaration.search(head).start()]))) != 1 or PLAN.search(head) or ASSERTED.search(head):
            continue
        if re.search(r'上述|前述|以上|这项|该项|它|其|两项|共同|均|都|同样|也(?:要|会|将)|前提|\b(?:it|these|both|same)\b', tail, re.I):
            continue
        return [(0,cut),(cut,len(text))]
    return fallback


SCOPED_V22_GUARD_VERSION = 'condition-scope-v3-distinct-projects'


def scoped_evidence_ranges_v22(text):
    """Release only two self-contained first-person, distinct named projects.

    A condition on one project must not contaminate a preceding independent
    wish for another. This narrow lexical split is NOT semantic entailment.
    Lists, quotations, shared scope, omitted subjects and named cross-project
    dependencies retain the complete passage. Historic method versions are
    unchanged. Sentence order alone does not establish scope independence.
    """
    fallback = scoped_evidence_ranges_v19(text)
    if not CONDITION.search(text):
        return fallback
    if LIST.search(text) or re.search(
        r'说|表示|认为|转述|引述|原话|写道|来信|访谈|转发|以下|下面|'
        r'[“”「」《》"\[\]【】（）()]|[\'`]|'
        r'上述|前述|以上|这项|该项|它|其|两项|共同|均|都|同样|前提|只有|除非|'
        r'\b(?:said|says|both|same|these|it)\b', text, re.I):
        return fallback
    # Require exactly two complete sentences; postposed conditions remain
    # attached and additional context requires review rather than guessing.
    sentences = list(re.finditer(r'[^。！？!?\n]+[。！？!?]', text))
    if len(sentences) != 2 or ''.join(m.group() for m in sentences) != text:
        return fallback
    project = re.compile(r'项目\s+([A-Za-z][A-Za-z0-9_-]*)(?![A-Za-z0-9_-])')
    projects = [project.findall(m.group()) for m in sentences]
    if any(len(names) != 1 for names in projects) or projects[0][0].casefold() == projects[1][0].casefold():
        return fallback
    unconditional = re.compile(r'\s*我(?:希望|想要|期望|计划|打算|准备)项目\s+[A-Za-z][A-Za-z0-9_-]*')
    conditional = re.compile(r'\s*(?:如果|倘若|假如)[^。！？!?\n]{1,80}[，,]\s*我(?:希望|想要|期望|计划|打算|准备)')
    first, second = [m.group() for m in sentences]
    for plain, guarded in ((first, second), (second, first)):
        if (unconditional.match(plain) and not CONDITION.search(plain)
                and conditional.match(guarded) and len(list(CONDITION.finditer(guarded))) == 1):
            # A name in the antecedent or an explicit reference to the other
            # project creates a dependency, even when action subjects differ.
            antecedent = guarded.split('，', 1)[0].split(',', 1)[0]
            if project.search(antecedent) or any(name.casefold() in guarded.casefold() for name in project.findall(plain)):
                continue
            return [(0, sentences[0].end()), (sentences[0].end(), len(text))]
    return fallback
