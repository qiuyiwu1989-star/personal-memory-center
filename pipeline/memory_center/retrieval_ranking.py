"""Deterministic lexical ranking; relevance is not truth or permission.

No provider, source mutation, query expansion, or factual inference. Call only
with already owner/scope-filtered rows. A stable tie keeps input recency order.
"""
from dataclasses import dataclass
import re
import unicodedata

RETRIEVAL_VERSION = 'lexical-v2'
_CJK = r'\u3400-\u4dbf\u4e00-\u9fff'
_RUN = re.compile(fr'[{_CJK}]+|[a-z0-9_]+(?:[-.][a-z0-9_]+)*')
# Grammatical question wrappers only; deliberately no project/domain stopwords.
_WRAPPERS = ('请问', '请帮我', '帮我查一下', '我想知道', '告诉我', '有哪些',
             '是什么', '怎么样', '怎么', '如何', '是否', '什么', '我的', '我们')
_PAIR_STOPS = frozenset(('这是', '这个', '那个', '一种', '一些', '以及', '或者', '可以', '需要', '应该', '进行'))
_LATIN_STOPS = frozenset(('the', 'a', 'an', 'is', 'are', 'what', 'how', 'my', 'our', 'of', 'to', 'and', 'or'))


def _normal(text):
    return unicodedata.normalize('NFKC', str(text or '')).lower()


@dataclass(frozen=True)
class QueryTerms:
    phrases: tuple
    pairs: frozenset
    latin: frozenset
    single: tuple


def query_terms(query):
    text = _normal(query)
    for wrapper in _WRAPPERS:
        text = text.replace(wrapper, ' ')
    text = re.sub(r'[呢吗](?=[\s？?！!。.,，]*$)', ' ', text)
    phrases, pairs, latin, single = [], set(), set(), []
    for run in _RUN.findall(text):
        if re.fullmatch(fr'[{_CJK}]+', run):
            if len(run) == 1:
                single.append(run)
            elif run not in _PAIR_STOPS:
                phrases.append(run)
                pairs.update(run[i:i+2] for i in range(len(run)-1)
                             if run[i:i+2] not in _PAIR_STOPS)
        elif run not in _LATIN_STOPS:
            latin.add(run)
    return QueryTerms(tuple(dict.fromkeys(phrases)), frozenset(pairs),
                      frozenset(latin), tuple(dict.fromkeys(single)))


def _fields(row):
    governance = row.get('governance') or {}
    evidence = row.get('evidence_context') or {}
    return ((4.0, _normal(row.get('statement'))),
            (4.0, _normal(row.get('display_statement'))),
            (6.0, _normal(row.get('subject'))),
            (6.0, _normal(governance.get('subject_id'))),
            (3.0, _normal(row.get('source_title') or evidence.get('conversation_title'))),
            (1.5, _normal(row.get('scope'))),
            (1.0, _normal(row.get('topic'))))


def _score(row, terms):
    fields = _fields(row)
    hits = {pair for pair in terms.pairs if any(pair in text for _, text in fields)}
    latin_hits = {word for word in terms.latin if any(
        re.search(r'(?<![a-z0-9_])' + re.escape(word) + r'(?![a-z0-9_])', text)
        for _, text in fields)}
    # A two-character query is meaningful on its own. Longer phrases require
    # two distinct pairs (or their complete phrase), never isolated shared Han.
    full = any(phrase in text for phrase in terms.phrases for _, text in fields)
    single_exact = any(word == text for word in terms.single for _, text in fields[2:4])
    if not (latin_hits or full or len(hits) >= 2 or single_exact):
        return 0.0
    # Take the strongest field for each unit: translated/original duplicates
    # and repeated occurrences must not inflate retrieval scores.
    score = sum(max(weight for weight, text in fields if pair in text) for pair in hits)
    score += sum(max(weight for weight, text in fields if re.search(
        r'(?<![a-z0-9_])' + re.escape(word) + r'(?![a-z0-9_])', text)) * 2
                 for word in latin_hits)
    score += sum(max((weight for weight, text in fields if phrase in text), default=0) * 2
                 for phrase in terms.phrases)
    if single_exact:
        score += 12
    return score


def score_record(row, query):
    return _score(row, query_terms(query)) if query.strip() else 0.0


def rank_records(rows, query):
    """Return matched rows in relevance order, unchanged and stably tied.

    Empty query retains original order. Nonempty queries containing no
    meaningful lexical unit return [], which is not a quality success signal.
    """
    if not query.strip():
        return list(rows)
    terms = query_terms(query)
    scored = [(row, _score(row, terms)) for row in rows]
    return [row for row, score in sorted(scored, key=lambda entry: entry[1], reverse=True)
            if score > 0]


def legacy_rank_records(rows,query):
    """Preserved production baseline for comparisons, not semantic validation."""
    if not query.strip():return list(rows)
    terms=set(re.findall(r'[a-z0-9_]+|[\u4e00-\u9fff]',query.lower()))
    def score(row):
        text=' '.join(str(row.get(k) or '') for k in ('statement','display_statement','subject','topic')).lower()
        return sum(t in text for t in terms)+5*(query.lower() in text)
    return sorted((row for row in rows if score(row)),key=score,reverse=True)


def search_records(rows,query,mode='lexical-v1'):
    if mode=='lexical-v1':return legacy_rank_records(rows,query)
    if mode==RETRIEVAL_VERSION:return rank_records(rows,query)
    raise ValueError('Unknown retrieval mode')
