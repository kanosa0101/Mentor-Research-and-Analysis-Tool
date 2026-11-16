/* Account-scoped library. No account data is copied to browser storage. */
(function(){
  'use strict';
  let data=null,revision=0,queue=Promise.resolve();
  let ready,loading,hasLoaded=false,resolveInitial;
  const initialReady=new Promise(resolve=>{resolveInitial=resolve;});
  window.addEventListener('account-session-expired',()=>{data=core()?.empty()||null;revision=0;document.getElementById('library-connection-message')?.remove();window.dispatchEvent(new CustomEvent('browser-library-change'));});
  const core=()=>window.BrowserLibraryCore;
  const read=()=>{if(!data)return core().empty();return core().validate(data);};
  function connectionMessage(){
    if(!OnlineAccount.state.authenticated||document.getElementById('library-connection-message'))return;
    const note=document.createElement('p'),button=document.createElement('button');note.id='library-connection-message';note.className='notice';note.setAttribute('role','status');
    note.append('收藏与待办暂时无法读取，当前页面输入已保留。');button.type='button';button.textContent='重新读取收藏与待办';
    button.onclick=async()=>{button.disabled=true;try{await reload();}catch(error){button.disabled=false;}};
    note.append(' ',button);(document.querySelector('main')||document.body).prepend(note);
  }
  const domReady=new Promise(resolve=>document.readyState==='loading'?document.addEventListener('DOMContentLoaded',resolve,{once:true}):resolve());
  function reload(){
    if(loading)return loading;
    ready=loading=(async()=>{
      await domReady;await OnlineAccount.currentRead;
      if(!core())return;
      if(!OnlineAccount.state.authenticated){data=core().empty();revision=0;document.getElementById('library-connection-message')?.remove();return;}
      const {response,data:value}=await OnlineAccount.readJSON('/api/library',{cache:'no-store'});
      if(!response.ok)throw new Error(value.error||'收藏与待办暂不可读取');
      if(!OnlineAccount.state.authenticated)return;
      data=core().validate(value.library||core().empty());revision=value.revision;
      document.getElementById('library-connection-message')?.remove();
      window.dispatchEvent(new CustomEvent('browser-library-change'));
    })().then(value=>{hasLoaded=true;resolveInitial(value);return value;}).catch(error=>{connectionMessage();throw error;}).finally(()=>{loading=null;});
    ready.catch(()=>{});return ready;
  }
  reload();
  window.addEventListener('account-session-ready',()=>{reload().catch(()=>{});});
  function mutate(action){
    const operation=queue.then(async()=>{
      await ready;
      if(!OnlineAccount.state.authenticated){location.assign(OnlineAccount.loginUrl());throw new Error('请登录后保存到账号');}
      const next=core().validate(action(read())),response=await fetch('/api/library',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision,library:next})}),value=await response.json();
      if(response.status===409){await reload();window.dispatchEvent(new CustomEvent('browser-library-change'));throw new Error('其他页面或设备已更新记录，已加载最新内容，请重新操作');}
      if(!response.ok)throw new Error(value.error||'保存失败，请重试');
      if(!OnlineAccount.state.authenticated)throw new Error('登录已失效，请重新登录后查看保存结果');
      data=core().validate(value.library||next);revision=value.revision;
      window.dispatchEvent(new CustomEvent('browser-library-change'));return read();
    });queue=operation.catch(()=>{});return operation;
  }
  window.CloudLibrary={get ready(){return hasLoaded?ready:initialReady;},read,mutate,reload};
})();
