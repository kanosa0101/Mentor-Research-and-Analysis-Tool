/* Saved account bookmarks, shown after the server confirms persistence. */
(function(){
  'use strict';
  const core=window.BrowserLibraryCore;if(!core)return;
  const prefix=/\/p\/[^/]+\.html$/.test(location.pathname)?'../':'';
  function notify(){window.dispatchEvent(new CustomEvent('browser-library-change'));}
  async function save(item){let result;await CloudLibrary.mutate(data=>{result=core.bookmark(data,item);return result.data;});return result;}
  function add(container,item){
    if(!container)return;
    const existing=container.querySelector('[data-browser-bookmark]');
    if(existing){
      if(existing.dataset.bookmarkId&&!existing.browserRefresh){existing.browserRefresh=()=>{const saved=CloudLibrary.read().bookmarks.some(b=>b.kind===item.kind&&b.url===core.safeUrl(item.url));existing.textContent=saved?'已收藏':'收藏到我的账号';existing.setAttribute('aria-pressed',String(saved));};existing.browserRefresh();}
      return;
    }
    const row=document.createElement('div');row.className='browser-library-action';
    const button=document.createElement('button');button.type='button';button.dataset.browserBookmark=item.kind;
    const message=document.createElement('span');message.setAttribute('role','status');message.style.fontSize='13px';
    function label(){try{const exists=CloudLibrary.read().bookmarks.some(b=>b.kind===item.kind&&b.url===core.safeUrl(item.url));button.textContent=exists?'已收藏':'收藏到我的账号';button.setAttribute('aria-pressed',String(exists));}catch(error){button.textContent='收藏到我的账号';}}
    button.onclick=async()=>{button.disabled=true;try{const result=await save(item);message.replaceChildren();message.append(result.duplicate?'已在账号中收藏。':'已保存到账号，可跨设备查看。');const link=document.createElement('a');link.href=prefix+'start.html#library';link.textContent='查看收藏 →';message.append(' ',link);label();}catch(error){message.textContent='未保存：'+error.message;}finally{button.disabled=false;}};
    button.browserRefresh=label;row.append(button,message);container.append(row);label();
  }
  function refreshButtons(){
    for(const card of document.querySelectorAll('[data-candidate]')){
      const title=card.querySelector('h2')?.textContent.trim();if(title)add(card,{kind:'mentor',title,url:card.querySelector('h2 a')?.getAttribute('href')||'p/'+encodeURIComponent(card.dataset.candidate)+'.html'});
    }
    for(const card of document.querySelectorAll('[data-opportunity]')){
      const title=card.querySelector('h2')?.textContent.trim();if(title)add(card,{kind:'opportunity',title,url:'opportunities.html?id='+encodeURIComponent(card.dataset.opportunity)});
    }
    for(const card of document.querySelectorAll('[data-notice-id]')){
      const title=card.querySelector('a.title')?.textContent.trim(),[school,dept]=(card.dataset.school||'').split('/');if(title){const query=new URLSearchParams({notice_cycle:'all',q:title});if(school)query.set('school',school);if(dept)query.set('dept',dept);add(card,{kind:'notice',title,url:'notices.html?'+query});}
    }
    if(prefix){const heading=document.querySelector('.wrap .card h2')||document.querySelector('h1');if(heading){const name=heading.cloneNode(true);name.querySelectorAll('.tag').forEach(tag=>tag.remove());add(document.querySelector('.context-actions')||heading.parentElement,{kind:'mentor',title:name.textContent.trim(),url:'p/'+location.pathname.split('/').pop()+location.search});}}
  }
  const style=document.createElement('style');style.textContent='.browser-library-action{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:14px}.browser-library-action button{min-height:40px}.browser-library-action span{line-height:1.7;overflow-wrap:anywhere}';document.head.append(style);
  let scheduled=false;
  const observer=new MutationObserver(()=>{if(scheduled)return;scheduled=true;queueMicrotask(()=>{scheduled=false;refreshButtons();});});
  observer.observe(document.body,{childList:true,subtree:true});
  window.addEventListener('browser-library-change',()=>document.querySelectorAll('[data-browser-bookmark]').forEach(button=>button.browserRefresh?.()));
  window.addEventListener('storage',event=>{if(event.key===core.KEY)notify();});
  window.BrowserLibrary={save,refreshButtons};refreshButtons();CloudLibrary.ready.then(()=>{document.querySelectorAll('[data-browser-bookmark]').forEach(button=>button.browserRefresh?.());}).catch(()=>{});
})();
