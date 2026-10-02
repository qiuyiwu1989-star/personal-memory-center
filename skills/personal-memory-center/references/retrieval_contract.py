"""Portable reference reader: injected MCP transport, no credentials or writes."""
import json


def _data(response):
    if isinstance(response,dict) and response.get('isError'):
        raise ValueError('MCP tool error; stop and recheck permission/version')
    if isinstance(response,dict) and isinstance(response.get('structuredContent'),dict):
        return response['structuredContent']
    if isinstance(response,dict) and isinstance(response.get('content'),list):
        texts=[c['text'] for c in response['content'] if c.get('type')=='text']
        if len(texts)==1:return json.loads(texts[0])
    return response


class Reader:
    """Explicit expansion only; an empty L1 never triggers an L2 search."""
    def __init__(self,call,scope,access_epoch=None,version=None):
        self.call=call
        self.identity=None
        self.reset(scope,access_epoch,version)

    def reset(self,scope,access_epoch=None,version=None):
        identity=(scope,access_epoch,version)
        if identity!=self.identity:
            self.locators={}
            self.identity=identity
        self.scope=scope

    def _call(self,name,arguments):
        try:
            result=_data(self.call(name,dict(arguments,scope=self.scope)))
        except (PermissionError,ValueError):
            self.locators={}
            raise
        if not isinstance(result,dict):raise ValueError('Invalid MCP response')
        if len(json.dumps(result,ensure_ascii=False,separators=(',',':'))) > arguments['max_chars']:
            self.locators={}
            raise ValueError('Response exceeds declared JSON budget')
        return result

    def background(self,needed,query):
        if not needed:return None
        return self._call('memory_context',{'query':query,'max_chars':1600})

    def search(self,query,kind='candidate'):
        if kind=='candidate':
            return self._call('memory_search',{'query':query,'max_chars':4000})
        if kind!='archive':raise ValueError('Explicit candidate/archive kind required')
        result=self._call('memory_archive_search',{'query':query,'max_chars':6000,'offset':0,'limit':20})
        for hit in result.get('results',[]):
            locator=hit['locator']
            self.locators[json.dumps(locator,sort_keys=True)]=locator.copy()
        return result

    def page(self,locator,offset=0,max_chars=4000):
        if type(offset) is not int or offset<0 or type(max_chars) is not int or not 500<=max_chars<=4000:
            raise ValueError('Invalid source page budget or offset')
        key=json.dumps(locator,sort_keys=True)
        if key not in self.locators:raise ValueError('Search again after scope/access/version change')
        result=self._call('memory_archive_source_get',{'locator':locator,'offset':offset,'max_chars':max_chars})
        if result.get('locator')!=locator:
            self.locators={}
            raise ValueError('Source version locator changed')
        return result

    def next_page(self,page,max_chars=4000):
        offset=page.get('next_offset')
        if offset is None:return None
        return self.page(page['locator'],offset,max_chars)
