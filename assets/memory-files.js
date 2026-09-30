/* Local text parsing only. File contents remain untrusted source material. */
(function(root){
  'use strict';
  const MAX_FILE_BYTES=1000000, MAX_TEXT_CHARS=200000, PART_CHARS=15000;
  function decode(name,bytes){
    if(!/\.(txt|md|markdown|json)$/i.test(name)) throw Error('暂时支持 TXT、Markdown 和 JSON，请先导出为文本。');
    if(bytes.byteLength>MAX_FILE_BYTES) throw Error('文件超过 1 MB；请使用归档导入流程。');
    let text;
    try{text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);}catch(e){throw Error('文件不是 UTF-8 文本，请转换编码后重试。');}
    if(text.includes('\0'))throw Error('文件包含二进制内容，无法作为文本读取。');
    if(!text.trim())throw Error('文件内容为空。');
    if(text.length>MAX_TEXT_CHARS)throw Error('正文超过 200,000 字符；请使用归档导入流程。');
    if(/\.json$/i.test(name)){try{JSON.parse(text);}catch(e){throw Error('JSON 格式无效，请检查文件。');}}
    return text;
  }
  function split(text){
    if(typeof text!=='string'||!text.trim())throw Error('正文不能为空。');
    if(text.length>MAX_TEXT_CHARS)throw Error('正文超过 200,000 字符；请使用归档导入流程。');
    const parts=[];
    for(let start=0;start<text.length;){
      let end=Math.min(start+PART_CHARS,text.length);
      if(end<text.length){
        const newline=text.lastIndexOf('\n',end);
        if(newline>start+PART_CHARS*0.6)end=newline+1;
        if(end<text.length && /[\uD800-\uDBFF]/.test(text[end-1]) && /[\uDC00-\uDFFF]/.test(text[end]))end--;
      }
      if(JSON.stringify(text.slice(start,end)).length>18000){
        let low=start+1,high=end;
        while(low<high){const mid=Math.ceil((low+high)/2);if(JSON.stringify(text.slice(start,mid)).length<=18000)low=mid;else high=mid-1;}
        end=low;
        if(end<text.length && /[\uD800-\uDBFF]/.test(text[end-1]) && /[\uDC00-\uDFFF]/.test(text[end]))end--;
      }
      parts.push(text.slice(start,end));start=end;
    }
    return parts;
  }
  const api={decode,split,MAX_FILE_BYTES,MAX_TEXT_CHARS};
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.MemoryFiles=api;
})(typeof window==='object'?window:globalThis);
