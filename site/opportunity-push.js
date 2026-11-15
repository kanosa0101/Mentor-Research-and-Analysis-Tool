const pushNode=id=>document.getElementById(id);
let pushConfig=null,pushRegistration=null;
function pushReceipt(){try{return JSON.parse(localStorage.getItem('mentor-push')||'null');}catch(error){return null;}}
async function pushRequest(action,body){
  const response=await fetch('/api/push/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const result=await response.json();if(!response.ok)throw new Error(result.error||'通知服务暂不可用');return result;
}
async function updatePushPanel(){
  try{
    const response=await fetch('/api/push/config');if(!response.ok)throw new Error();pushConfig=await response.json();
    const secure=pushConfig.origin&&location.origin===pushConfig.origin&&window.isSecureContext;
    if(!pushConfig.enabled||!secure){
      pushNode('push-status').textContent=pushConfig.enabled?'请在本站 HTTPS 页面订阅浏览器通知。':'浏览器通知暂不可用，请查看站内更新记录。';
      if(pushConfig.origin){const link=document.createElement('a');link.href=pushConfig.origin+'/opportunities.html';link.textContent='打开 HTTPS 通知站点 →';pushNode('push-status').append(' ',link);}
      return;
    }
    if(!('serviceWorker' in navigator)||!('PushManager' in window)||!('Notification' in window)){pushNode('push-status').textContent='当前浏览器不支持后台推送，可以查看下方更新记录。';return;}
    pushRegistration=await navigator.serviceWorker.register('opportunity-sw.js');await navigator.serviceWorker.ready;
    pushNode('push-subscribe').disabled=false;
    pushNode('push-unsubscribe').hidden=!pushReceipt();pushNode('push-test').hidden=!pushReceipt();
    pushNode('push-status').textContent=pushReceipt()?'已保存订阅。更新条件时点击“按当前筛选订阅”；关闭本页后由浏览器接收。':'点击后由浏览器询问通知权限；不会自动发送邮件或上传私人申请记录。';
  }catch(error){pushNode('push-status').textContent='暂时无法连接通知服务，请稍后刷新。';}
}
pushNode('push-subscribe').onclick=async()=>{
  pushNode('push-subscribe').disabled=true;
  try{
    if(await Notification.requestPermission()!=='granted')throw new Error('通知权限未允许，请在浏览器站点设置中开启。');
    const key=Uint8Array.from(atob(pushConfig.public_key.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0));
    const subscription=await pushRegistration.pushManager.getSubscription()||await pushRegistration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:key});
    const filters={school:pushNode('opportunity-school').value,kind:pushNode('opportunity-kind').value,year:pushNode('opportunity-year').value,query:pushNode('opportunity-search').value,discoveries:pushNode('push-discoveries').checked};
    const receipt=await pushRequest('subscribe',{subscription:subscription.toJSON(),filters,token:pushReceipt()?.token});
    localStorage.setItem('mentor-push',JSON.stringify(receipt));pushNode('push-status').textContent='已订阅当前筛选条件：已核验机会更新和明确截止提醒'+(filters.discoveries?'，包含待核验公告。':'。');
    pushNode('push-unsubscribe').hidden=false;pushNode('push-test').hidden=false;
  }catch(error){pushNode('push-status').textContent='订阅未完成：'+error.message;}
  finally{pushNode('push-subscribe').disabled=false;}
};
pushNode('push-unsubscribe').onclick=async()=>{
  try{
    const receipt=pushReceipt();if(receipt)await pushRequest('unsubscribe',receipt);
    const subscription=await pushRegistration?.pushManager.getSubscription();if(subscription)await subscription.unsubscribe();
    localStorage.removeItem('mentor-push');pushNode('push-status').textContent='已退订，服务器不再向此订阅发送更新。';pushNode('push-unsubscribe').hidden=true;pushNode('push-test').hidden=true;
  }catch(error){pushNode('push-status').textContent='退订尚未确认：'+error.message;}
};
pushNode('push-test').onclick=async()=>{
  pushNode('push-test').disabled=true;
  try{await pushRequest('test',pushReceipt());pushNode('push-status').textContent='推送服务已接受测试，请检查浏览器或系统通知；接受不等于已经显示。';}
  catch(error){pushNode('push-status').textContent='测试未完成：'+error.message;}
  finally{pushNode('push-test').disabled=false;}
};
async function loadUpdateHistory(){
  try{
    const response=await fetch('/api/updates');if(!response.ok)throw new Error();const data=await response.json();
    const list=pushNode('update-history');list.replaceChildren();
    for(const event of data.events.slice(0,15)){const p=document.createElement('p'),a=document.createElement('a');a.href=event.url.startsWith('/opportunities.html')?event.url:'/opportunities.html';a.textContent=event.title;p.append(a,' · '+new Date(event.created_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}));list.append(p);}
    if(!data.events.length)list.textContent='尚无后续更新记录。首次收录建立基线，不追发历史通知。';
  }catch(error){pushNode('update-history').textContent='更新记录暂不可读取。';}
}
updatePushPanel();loadUpdateHistory();
