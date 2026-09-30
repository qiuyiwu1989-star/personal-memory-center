"""Character-bounded Markdown pages including the serialized response envelope."""
from .core import Invalid, encoded


def page(document, offset=0, max_chars=4000):
    if type(offset) is not int or offset < 0 or type(max_chars) is not int or not 500 <= max_chars <= 16000:
        raise Invalid('分页预算无效')
    text = document['markdown']
    if offset > len(text): raise Invalid('分页位置超出文档')
    result = {k:document[k] for k in ('slug','title','revision')}
    result.update(markdown='',offset=offset,next_offset=None,total_chars=len(text))
    end = min(len(text),offset+max_chars)
    while True:
        result.update(markdown=text[offset:end], next_offset=end if end < len(text) else None)
        excess = len(encoded(result))-max_chars
        if excess <= 0: return result
        if end <= offset: raise Invalid('文档标题超过读取预算')
        end = max(offset,end-excess)
