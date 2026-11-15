self.addEventListener('push',event=>{
  let data={title:'导师库信息更新',body:'打开站点查看更新。',url:'/opportunities.html'};
  try{Object.assign(data,event.data.json());}catch(error){}
  const url=typeof data.url==='string'&&data.url.startsWith('/opportunities.html')?data.url:'/opportunities.html';
  event.waitUntil(self.registration.showNotification(data.title,{body:data.body,tag:data.tag||'mentor-update',data:{url}}));
});
self.addEventListener('notificationclick',event=>{
  event.notification.close();
  event.waitUntil(clients.openWindow(new URL(event.notification.data.url,self.location.origin).href));
});
