/* Browser-only planning data. This module never sends a network request. */
(function(root){
  'use strict';
  const KEY='mentor-browser-library-v1',KINDS=['mentor','notice','opportunity'];
  const empty=()=>({version:1,targets:[],bookmarks:[],todos:[]});
  const check=(condition,message)=>{if(!condition)throw new Error(message);};
  const text=(value,max,allowEmpty=false)=>typeof value==='string'&&value.length<=max&&(allowEmpty||value.trim().length>0);
  const fields=(item,keys)=>item&&typeof item==='object'&&!Array.isArray(item)&&Object.keys(item).sort().join('|')===keys.slice().sort().join('|');
  const validId=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,96}$/.test(value);
  const validYear=value=>Number.isInteger(value)&&value>=2000&&value<=2100;
  function validDate(value){return typeof value==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(value)&&!Number.isNaN(Date.parse(value))&&new Date(value+'T00:00:00Z').toISOString().slice(0,10)===value;}
  function safeUrl(value){
    check(text(value,3000),'收藏链接无效');
    check(!/^[a-z][a-z\d+.-]*:|^\/\/|\\|[\u0000-\u0020]/i.test(value),'备份只接受本站页面链接');
    check(!/%|(^|\/)\.{1,2}(\/|$)/.test(value.split(/[?#]/)[0]),'收藏路径不能包含编码或目录跳转');
    const url=new URL(value,'https://browser-library.invalid/');
    check(url.origin==='https://browser-library.invalid'&&!url.username&&!url.password,'备份链接不能离开本站');
    check(/^\/(?:start|discovery|notices|opportunities|admissions|compare|desk|applications)\.html$/.test(url.pathname)||/^\/p\/[A-Za-z0-9_-]+\.html$/.test(url.pathname),'不支持的收藏页面');
    return url.pathname.slice(1)+url.search+url.hash;
  }
  function validate(data){
    check(fields(data,['version','targets','bookmarks','todos'])&&data.version===1,'不是本产品的浏览器备份');
    for(const [key,max] of [['targets',50],['bookmarks',500],['todos',1000]])check(Array.isArray(data[key])&&data[key].length<=max,'备份条目过多或结构错误');
    const ids=new Set();
    for(const item of [...data.targets,...data.bookmarks,...data.todos]){
      check(validId(item?.id)&&!ids.has(item.id),'条目标识无效或重复');ids.add(item.id);
      check(validDate(item.created_at),'保存日期无效');
    }
    for(const target of data.targets){
      check(fields(target,['id','path','year','schools','interest','created_at'])&&['exam','recommend'].includes(target.path)&&validYear(target.year),'关注目标无效');
      check(text(target.interest,200,true)&&Array.isArray(target.schools)&&target.schools.length<=20,'目标兴趣或学校数量无效');
      const schools=new Set();
      for(const school of target.schools){check(fields(school,['id','name'])&&validId(school.id)&&text(school.name,100)&&!schools.has(school.id),'目标学校无效或重复');schools.add(school.id);}
    }
    for(const bookmark of data.bookmarks){
      check(fields(bookmark,['id','kind','title','url','created_at'])&&KINDS.includes(bookmark.kind)&&text(bookmark.title,300),'收藏条目无效');
      check(safeUrl(bookmark.url)===bookmark.url,'收藏地址须为规范本站链接');
    }
    const targetIds=new Set(data.targets.map(t=>t.id));
    for(const todo of data.todos){
      check(fields(todo,['id','title','done','due_date','target_id','created_at'])&&text(todo.title,300)&&typeof todo.done==='boolean','待办条目无效');
      check(todo.due_date===''||validDate(todo.due_date),'待办日期无效');
      check(todo.target_id===''||targetIds.has(todo.target_id),'待办关联的关注目标不存在');
    }
    return JSON.parse(JSON.stringify(data));
  }
  function parse(raw){check(typeof raw==='string'&&raw.length<=2000000,'备份文件过大');let data;try{data=JSON.parse(raw);}catch(error){throw new Error('备份不是有效的 JSON 文件');}return validate(data);}
  const read=storage=>{const raw=storage.getItem(KEY);return raw===null?empty():parse(raw);};
  const write=(storage,data)=>{const valid=validate(data);storage.setItem(KEY,JSON.stringify(valid));return valid;};
  function merge(current,incoming){
    const base=validate(current),extra=validate(incoming),ids=new Set([...base.targets,...base.bookmarks,...base.todos].map(x=>x.id));
    const urls=new Set(base.bookmarks.map(b=>b.kind+'|'+b.url));
    for(const key of ['targets','bookmarks','todos'])for(const item of extra[key]){
      if(ids.has(item.id)||key==='bookmarks'&&urls.has(item.kind+'|'+item.url))continue;
      base[key].push(item);ids.add(item.id);if(key==='bookmarks')urls.add(item.kind+'|'+item.url);
    }
    return validate(base);
  }
  function remove(data,kind,id){
    check(['targets','bookmarks','todos'].includes(kind),'删除类型无效');
    const copy=validate(data);copy[kind]=copy[kind].filter(item=>item.id!==id);
    if(kind==='targets')for(const todo of copy.todos)if(todo.target_id===id)todo.target_id='';
    return copy;
  }
  const id=prefix=>prefix+'_'+Date.now().toString(36)+'_'+Math.random().toString(36).slice(2,10);
  const day=()=>new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'});
  function bookmark(data,item){
    const copy=validate(data),url=safeUrl(item.url);
    const old=copy.bookmarks.find(row=>row.kind===item.kind&&row.url===url);
    if(old)return {data:copy,item:old,duplicate:true};
    const row={id:id('bookmark'),kind:item.kind,title:item.title,url,created_at:day()};
    copy.bookmarks.push(row);return {data:validate(copy),item:row,duplicate:false};
  }
  const api={KEY,empty,validate,parse,read,write,merge,remove,bookmark,safeUrl,id,day};
  if(typeof module!=='undefined')module.exports=api;else root.BrowserLibraryCore=api;
})(typeof window!=='undefined'?window:globalThis);
