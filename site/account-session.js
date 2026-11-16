/* Same-origin account session shared by the online pages. */
(function(){
  'use strict';
  const nativeFetch=window.fetch.bind(window),state={authenticated:false,user:null,csrf_token:''};
  let ready,reading,failure=null,hasSession=false,resolveInitial;
  const initialReady=new Promise(resolve=>{resolveInitial=resolve;});
  function loginUrl(next=location.pathname+location.search+location.hash){return '/account.html?next='+encodeURIComponent(next);}
  async function readJSON(input,options={}){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),8000);
    try{
      const response=await window.fetch(input,{...options,signal:controller.signal});
      const data=await response.json();return {response,data};
    }catch(error){
      if(controller.signal.aborted)throw Object.assign(new Error('读取超时，请重试'),{timedOut:true});
      throw error;
    }finally{clearTimeout(timer);}
  }
  function connectionMessage(){
    if(!failure)return;
    if(!document.body){document.addEventListener('DOMContentLoaded',connectionMessage,{once:true});return;}
    if(document.getElementById('account-connection-message'))return;
    const note=document.createElement('p'),button=document.createElement('button');note.id='account-connection-message';note.className='notice';note.setAttribute('role','status');
    note.append('账号暂时无法读取，当前页面输入已保留。');button.type='button';button.textContent='重新连接账号';
    button.onclick=async()=>{button.disabled=true;try{await refresh();}catch(error){button.disabled=false;}};
    note.append(' ',button);(document.querySelector('main')||document.body).prepend(note);
  }
  function refresh(){
    if(reading)return reading;
    ready=reading=(async()=>{
      const {response,data}=await readJSON('/api/auth/me',{cache:'no-store'});
      if(!response.ok)throw new Error('账号服务暂不可用，请重试');
      Object.assign(state,data);failure=null;hasSession=true;resolveInitial(state);document.getElementById('account-connection-message')?.remove();
      document.querySelectorAll('[data-account-link]').forEach(a=>{a.textContent=state.authenticated?'我的账号':'登录 / 注册';a.href=loginUrl();});
      window.dispatchEvent(new CustomEvent('account-session-ready'));
      return state;
    })().catch(error=>{failure=error;connectionMessage();throw error;}).finally(()=>{reading=null;});
    ready.catch(()=>{});return ready;
  }
  refresh();
  function expired(){
    const wasLoggedIn=state.authenticated;
    Object.assign(state,{authenticated:false,user:null,csrf_token:''});
    window.dispatchEvent(new CustomEvent('account-session-expired'));
    document.querySelectorAll('[data-account-link]').forEach(a=>{a.textContent='登录 / 注册';a.href=loginUrl();});
    if(wasLoggedIn&&!document.getElementById('account-expired-message')){
      const note=document.createElement('p');note.id='account-expired-message';note.setAttribute('role','status');
      note.append('登录已失效，已保存的记录仍在账号中。');const link=document.createElement('a');link.href=loginUrl();link.textContent='重新登录后继续 →';note.append(' ',link);
      (document.querySelector('main')||document.body).prepend(note);
    }
  }
  // Existing page initializers can finish after recovery; writes use the current
  // attempt below, so a failed save is never replayed when initialization resumes.
  window.OnlineAccount={state,get ready(){return hasSession?ready:initialReady;},get currentRead(){return ready;},refresh,loginUrl,readJSON};
  window.fetch=async function(input,options={}){
    const url=new URL(typeof input==='string'||input instanceof URL?input:input.url,location.href);
    if(url.origin!==location.origin||!url.pathname.startsWith('/api/'))return nativeFetch(input,options);
    const method=(options.method||input?.method||'GET').toUpperCase();
    if(!['GET','HEAD','OPTIONS'].includes(method)&&/^\/api\/(auth\/(logout|password)|library|workflow|materials|outreach|restore|discovery)(?:\/|$)/.test(url.pathname)){
      await ready;
      const headers=new Headers(options.headers||input?.headers);
      if(state.csrf_token)headers.set('X-CSRF-Token',state.csrf_token);
      options={...options,headers};
    }
    const response=await nativeFetch(input,options);
    if(response.status===401){expired();if(/^\/(desk|applications|board)\.html$/.test(location.pathname))location.replace(loginUrl());}
    return response;
  };
  document.addEventListener('DOMContentLoaded',()=>{ready.then(()=>document.querySelectorAll('[data-account-link]').forEach(a=>{a.textContent=state.authenticated?'我的账号':'登录 / 注册';a.href=loginUrl();})).catch(()=>{});});
  window.addEventListener('pageshow',event=>{if(event.persisted)location.reload();});
  window.addEventListener('storage',event=>{if(event.key==='mentor-account-change')location.reload();});
})();
