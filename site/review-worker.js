self.addEventListener('push',event=>{
  let message={};try{message=event.data?event.data.json():{};}catch{return;}
  const title=typeof message.title==='string'?message.title.slice(0,100):'审核待办提醒';
  let url='/review.html';try{const candidate=new URL(message.url||url,self.location.origin);if(candidate.origin===self.location.origin&&candidate.pathname==='/review.html')url=candidate.pathname+candidate.search;}catch{}
  event.waitUntil(self.registration.showNotification(title,{body:typeof message.body==='string'?message.body.slice(0,300):'请打开本机工作台检查待处理审核。',tag:typeof message.tag==='string'?message.tag:'review-maintenance',data:{url}}));
});
self.addEventListener('notificationclick',event=>{
  event.notification.close();
  let target=new URL('/review.html',self.location.origin);try{const candidate=new URL(event.notification.data?.url||'/review.html',self.location.origin);if(candidate.origin===target.origin&&candidate.pathname===target.pathname)target=candidate;}catch{}
  event.waitUntil(self.clients.matchAll({type:'window',includeUncontrolled:true}).then(async windows=>{const existing=windows.find(client=>{try{return new URL(client.url).origin===target.origin&&new URL(client.url).pathname==='/review.html';}catch{return false;}});if(existing){await existing.navigate(target.href);return existing.focus();}return self.clients.openWindow(target.href);}));
});
