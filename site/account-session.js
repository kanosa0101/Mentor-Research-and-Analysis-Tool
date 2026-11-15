/* Same-origin account session shared by the online pages. */
(function(){
  'use strict';
  const nativeFetch=window.fetch.bind(window),state={authenticated:false,user:null,csrf_token:''};
  function loginUrl(next=location.pathname+location.search+location.hash){return '/account.html?next='+encodeURIComponent(next);}
  async function refresh(){
    const response=await nativeFetch('/api/auth/me',{cache:'no-store'});
    if(!response.ok)throw new Error('账号服务暂不可用，请重试');
    Object.assign(state,await response.json());
    document.querySelectorAll('[data-account-link]').forEach(a=>{a.textContent=state.authenticated?'我的账号':'登录 / 注册';a.href=loginUrl();});
    return state;
  }
  const ready=refresh();ready.catch(()=>{});
  window.OnlineAccount={state,ready,refresh,loginUrl};
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
    if(response.status===401&&/^\/(desk|applications|board)\.html$/.test(location.pathname))location.replace(loginUrl());
    return response;
  };
  document.addEventListener('DOMContentLoaded',()=>{ready.then(()=>document.querySelectorAll('[data-account-link]').forEach(a=>{a.textContent=state.authenticated?'我的账号':'登录 / 注册';a.href=loginUrl();})).catch(()=>{});});
  window.addEventListener('pageshow',event=>{if(event.persisted)location.reload();});
  window.addEventListener('storage',event=>{if(event.key==='mentor-account-change')location.reload();});
})();
