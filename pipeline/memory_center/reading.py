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


def source_page(source_key, message, offset=0, max_chars=4000):
    if type(offset) is not int or offset < 0 or type(max_chars) is not int or not 500<=max_chars<=16000:
        raise Invalid('原文分页预算无效')
    text=message['text']
    if offset>len(text):raise Invalid('原文分页位置无效')
    end=min(len(text),offset+max_chars)
    while True:
        result={'source_key':source_key,'message':dict(message,text=text[offset:end]),'offset':offset,
                'next_offset':end if end<len(text) else None,'total_chars':len(text)}
        excess=len(encoded(result))-max_chars
        if excess<=0:return result
        if end<=offset:raise Invalid('原文元信息超过读取预算')
        end=max(offset,end-excess)


def search_page(snapshot,max_chars=6000):
    """Bound the full JSON candidate response, including envelope and escaping."""
    if type(max_chars) is not int or not 500<=max_chars<=16000:raise Invalid('检索预算无效')
    result={'records':[],'total':snapshot['total'],'truncated':True}
    base_size=len(encoded(result));items_size=0
    # Exact JSON length arithmetic preserves whole-item/skip-oversize behavior
    # without repeatedly encoding all already selected rows for every match.
    fields=('id','statement','subject','status','source_id','message_id','source_date','revision','governance')
    minimum={key:'' for key in fields};minimum.update(revision=0,governance={})
    lower_bound=len(encoded(minimum))
    for row in snapshot['records']:
        count=len(result['records'])+1
        overhead=base_size+items_size+2*(count-1)
        if overhead+lower_bound>max_chars:break
        item={key:row[key] for key in fields}
        size=len(encoded(item))
        truncated=count<snapshot['total']
        # JSON false is one character longer than true.
        if overhead+size+(0 if truncated else 1)<=max_chars:
            result['records'].append(item);items_size+=size
    result['truncated']=len(result['records'])<snapshot['total']
    return result


def fit_candidate_coverage(result,max_chars):
    """Keep the explicit ranking window in the same whole-response budget."""
    while len(encoded(result))>max_chars and result['records']:
        result['records'].pop()
    result['truncated']=len(result['records'])<result['total']
    if len(encoded(result))>max_chars:raise Invalid('候选覆盖元信息超过预算')
    return result
