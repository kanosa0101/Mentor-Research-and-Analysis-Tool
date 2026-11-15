(function(){
  'use strict';
  const $=id=>document.getElementById(id);let mode='login',busy=false;
  function next(){const raw=new URLSearchParams(location.search).get('next')||'/start.html';try{const u=new URL(raw,location.origin);if(u.origin===location.origin&&/^\/(?:start|desk|applications|board|discovery|opportunities|admissions|notices|compare)\.html$/.test(u.pathname))return u.pathname+u.search+u.hash;if(u.origin===location.origin&&/^\/p\/[A-Za-z0-9_-]+\.html$/.test(u.pathname))return u.pathname+u.search+u.hash;}catch(error){}return '/start.html';}
  function signal(userId){try{const previous=sessionStorage.getItem('mentor-account-id');if(!userId||previous&&previous!==userId)sessionStorage.removeItem('mentor-start-draft-v1');if(userId)sessionStorage.setItem('mentor-account-id',userId);else sessionStorage.removeItem('mentor-account-id');localStorage.setItem('mentor-account-change',String(Date.now()));}catch(error){}}
  function render(){const logged=OnlineAccount.state.authenticated;$('account-heading').textContent=logged?'我的账号':'登录后继续申请准备';$('account-form').hidden=logged;$('account-tabs').hidden=logged;$('account-signed-in').hidden=!logged;if(logged){$('account-name').textContent=OnlineAccount.state.user.username;$('account-continue').href=next();}}
  function tab(value){mode=value;$('account-submit').textContent=value==='login'?'登录并继续':'注册并继续';$('account-password').autocomplete=value==='login'?'current-password':'new-password';$('account-confirm-label').hidden=value==='login';$('account-confirm').required=value==='register';for(const b of document.querySelectorAll('[data-account-mode]'))b.setAttribute('aria-pressed',String(b.dataset.accountMode===value));$('account-message').textContent='';}
  document.querySelectorAll('[data-account-mode]').forEach(b=>b.onclick=()=>{if(!busy)tab(b.dataset.accountMode);});
  $('account-form').onsubmit=async event=>{
    event.preventDefault();if(busy)return;
    if(mode==='register'&&$('account-password').value!==$('account-confirm').value){$('account-message').textContent='两次输入的密码不一致。';return;}
    busy=true;$('account-submit').disabled=true;
    try{const response=await fetch('/api/auth/'+mode,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:$('account-username').value.trim(),password:$('account-password').value})}),value=await response.json();if(!response.ok)throw new Error(value.error||'操作未完成，请重试');signal(value.user.id);location.replace(next());}
    catch(error){$('account-message').textContent=error.message;}finally{busy=false;$('account-submit').disabled=false;}
  };
  $('account-logout').onclick=async()=>{if(busy)return;busy=true;try{await OnlineAccount.ready;const response=await fetch('/api/auth/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(!response.ok)throw new Error('退出未完成，请重试');signal(null);location.replace('/account.html');}catch(error){$('account-message').textContent=error.message;busy=false;}};
  $('password-form').onsubmit=async event=>{event.preventDefault();if(busy)return;busy=true;$('password-submit').disabled=true;try{const response=await fetch('/api/auth/password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({current_password:$('password-current').value,new_password:$('password-new').value})}),value=await response.json();if(!response.ok)throw new Error(value.error||'密码修改失败');Object.assign(OnlineAccount.state,value);$('password-form').reset();$('account-message').textContent='密码已修改，其他设备的会话已退出。';signal(value.user.id);}catch(error){$('account-message').textContent=error.message;}finally{busy=false;$('password-submit').disabled=false;}};
  OnlineAccount.ready.then(render).catch(error=>{$('account-message').textContent=error.message;});tab('login');
})();
