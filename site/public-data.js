(async function(){
  const host=document.getElementById('public-data-panel');if(!host)return;
  host.innerHTML='<h2>公共资料更新</h2><p id="public-data-status" role="status">正在检查运行方式…</p><button type="button" id="public-data-check">检查新版资料</button> <button type="button" id="public-data-update" hidden>更新公共资料</button><p class="muted">更新导师、政策、通知和机会资料，保留私人项目、材料、历史及保存快照。先保存其他页面的输入；更新期间请保持本机服务运行。</p>';
  const status=host.querySelector('#public-data-status'),check=host.querySelector('#public-data-check'),update=host.querySelector('#public-data-update');let candidate=null;
  const call=async(path,body)=>{const response=await fetch('/api/public-data'+path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const data=await response.json();if(!response.ok)throw new Error(data.error||'公共资料服务暂不可用');return data;};
  async function poll(){
    const current=await call('');
    if(current.mode==='public'){status.textContent='公开站已使用服务器发布的资料。私人申请仍由本机版管理。';check.hidden=true;update.hidden=true;return;}
    check.disabled=update.disabled=current.busy;
    status.textContent=current.message||(current.installed?'已更新至 '+current.installed.generated_at+' 发布的公共资料。':'当前使用运行包自带资料，可检查服务器新版。');
    if(current.busy)setTimeout(()=>poll().catch(e=>{status.textContent=e.message;}),2000);
  }
  check.onclick=async()=>{check.disabled=true;try{candidate=await call('/check',{});status.textContent='可用资料发布于 '+candidate.generated_at+'，要求客户端 '+candidate.client_version+'。更新前会校验文件并构建，失败保留原资料。';update.hidden=false;}catch(e){status.textContent=e.message;}finally{check.disabled=false;}};
  update.onclick=async()=>{if(!candidate||!confirm('已保存其他页面的输入？本次只更新公共资料，私人申请记录和已保存快照保持不变。'))return;update.disabled=true;try{await call('/update',{id:candidate.id});await poll();}catch(e){status.textContent=e.message;update.disabled=false;}};
  try{await poll();}catch(e){status.textContent='资料更新需要通过本机服务运行；静态网页不能更新文件。';check.disabled=true;}
})();
