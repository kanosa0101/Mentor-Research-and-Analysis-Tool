/* Account-scoped library. No account data is copied to browser storage. */
(function(){
  'use strict';
  let data=null,revision=0,queue=Promise.resolve();
  const core=()=>window.BrowserLibraryCore;
  const read=()=>{if(!data)return core().empty();return core().validate(data);};
  async function reload(){
    if(!core())return;
    if(!OnlineAccount.state.authenticated){data=core().empty();return;}
    const response=await fetch('/api/library',{cache:'no-store'}),value=await response.json();
    if(!response.ok)throw new Error(value.error||'收藏与待办暂不可读取');
    data=core().validate(value.library||core().empty());revision=value.revision;
  }
  const ready=new Promise(resolve=>document.readyState==='loading'?document.addEventListener('DOMContentLoaded',resolve,{once:true}):resolve()).then(()=>OnlineAccount.ready).then(reload);
  ready.catch(()=>{});
  function mutate(action){
    const operation=queue.then(async()=>{
      await ready;
      if(!OnlineAccount.state.authenticated){location.assign(OnlineAccount.loginUrl());throw new Error('请登录后保存到账号');}
      const next=core().validate(action(read())),response=await fetch('/api/library',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision,library:next})}),value=await response.json();
      if(response.status===409){await reload();window.dispatchEvent(new CustomEvent('browser-library-change'));throw new Error('其他页面或设备已更新记录，已加载最新内容，请重新操作');}
      if(!response.ok)throw new Error(value.error||'保存失败，请重试');
      data=core().validate(value.library||next);revision=value.revision;
      window.dispatchEvent(new CustomEvent('browser-library-change'));return read();
    });queue=operation.catch(()=>{});return operation;
  }
  window.CloudLibrary={ready,read,mutate,reload};
})();
