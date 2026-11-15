/* Convert saved account planning records to an application project. */
(function(){
  'use strict';
  const core=window.BrowserLibraryCore,el=(tag,text,className)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n;};
  if(!core)return;
  let mode='loading',selection=null,workflow=null,saving=false;
  const panel=document.getElementById('local-overview'),list=document.getElementById('local-next-actions');
  const dialog=document.createElement('dialog');dialog.id='plan-transfer-dialog';
  dialog.innerHTML='<form id="plan-transfer-form"><h2>建立申请项目</h2><p id="plan-source"></p><label id="plan-goal-label">关联关注目标<select id="plan-goal"></select></label><label>这次申请的学校<select id="plan-school"></select></label><label>项目名称<input id="plan-name" maxlength="300" required></label><label>个人备注（可选）<textarea id="plan-notes" maxlength="3000" rows="3"></textarea></label><p id="plan-preview" class="start-note"></p><p class="start-note">保存到账号，不会提交报名或发信。原关注与收藏记录保留；有日期的关联待办转为个人提醒，无日期待办保存在项目备注。</p><p id="plan-status" role="status"></p><div class="start-actions"><button type="submit" class="primary" id="plan-confirm">确认建立项目</button><button type="button" id="plan-cancel">取消</button></div></form>';
  document.body.append(dialog);
  const style=el('style');style.textContent='#plan-transfer-dialog{width:min(580px,calc(100% - 28px));max-height:90vh;overflow:auto;border:1px solid var(--line);border-radius:10px;padding:22px}#plan-transfer-dialog::backdrop{background:#152c2855}#plan-transfer-form label{display:grid;gap:6px;margin:14px 0}#plan-transfer-form input,#plan-transfer-form select,#plan-transfer-form textarea{width:100%;min-width:0;padding:10px;border:1px solid var(--line);border-radius:6px;font:inherit}#local-next-actions article{border-bottom:1px solid var(--line);padding:14px 0}#local-next-actions p{margin:6px 0;line-height:1.7}#local-next-actions a{margin-right:14px}#local-next-actions .personal-due{color:#945619}';document.head.append(style);
  const $=id=>document.getElementById(id),title=g=>g.path==='exam'?g.year+'年入学统考':g.year+'届保研准备';
  window.addEventListener('account-session-expired',()=>{
    mode='guest';selection=null;workflow=null;dialog.close();$('plan-transfer-form').reset();
    $('plan-source').textContent='';$('plan-preview').textContent='';$('plan-status').textContent='';$('plan-goal').replaceChildren();$('plan-school').replaceChildren();
    if(panel){panel.hidden=true;list.replaceChildren();$('local-overview-status').textContent='';}refresh();
  });
  const link=(name,url)=>{const n=el('a',name);n.href=url;return n;};
  async function api(path,body){const r=await fetch('/api/workflow'+path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const d=await r.json();if(!r.ok)throw new Error(d.error||'申请工作台暂不可用');return d;}
  function refresh(){
    for(const row of document.querySelectorAll('[data-plan-kind]')){
      let button=row.querySelector('[data-plan-convert]');
      if(!button){button=el('button');button.type='button';button.dataset.planConvert='';button.onclick=()=>open(row.dataset.planKind,row.dataset.planId);row.querySelector('.start-actions').prepend(button);}
      button.disabled=mode==='loading';button.textContent=mode==='online'?'建立申请项目':'登录后建立申请';
    }
  }
  function currentGoal(){return selection?.kind==='target'?selection.item:selection?.data.targets.find(g=>g.id===$('plan-goal').value)||null;}
  function preview(){
    const goal=currentGoal(),previous=$('plan-school').value,choices=goal?.schools||[];
    $('plan-school').replaceChildren(new Option(choices.length?'请选择一所学校':'暂不指定学校',''));
    for(const school of choices)$('plan-school').add(new Option(school.name,school.id));
    $('plan-school').value=choices.some(s=>s.id===previous)?previous:choices.length===1?choices[0].id:'';
    const todos=goal?selection.data.todos.filter(t=>t.target_id===goal.id):[];
    $('plan-preview').textContent=(goal?(goal.path==='recommend'?'本科毕业届别 '+goal.year+' 将写入备注，入学年份保持未知。':'计划入学年份 '+goal.year+'，请继续核对具体院系和专业。'):'未关联目标，资格与入学年份不作推断。')+' 关联待办 '+todos.length+' 条（'+todos.filter(t=>t.due_date).length+' 条有个人计划日期）。'+(selection.item.kind==='opportunity'?' 活动快照及入学年份以服务器发布的官方目录为准。':'');
  }
  function open(kind,id){
    if(mode!=='online'){
      location.assign(OnlineAccount.loginUrl());return;
    }
    try{
      const data=CloudLibrary.read(),item=data[kind==='target'?'targets':'bookmarks'].find(i=>i.id===id);if(!item)throw new Error('该账号记录已不存在，请刷新');
      selection={kind,item,data};$('plan-source').textContent='来自：'+(kind==='target'?title(item):item.title);
      $('plan-name').value=kind==='target'?(item.schools.length===1?item.schools[0].name+' · ':'')+title(item):item.title;
      $('plan-notes').value='';$('plan-status').textContent='';$('plan-confirm').disabled=false;
      $('plan-goal-label').hidden=kind==='target';$('plan-goal').replaceChildren(new Option('暂不关联',''));
      for(const goal of data.targets)$('plan-goal').add(new Option(title(goal)+' · '+(goal.schools.map(s=>s.name).join('、')||'跨校'),goal.id));
      preview();dialog.showModal();
    }catch(error){$('library-status').textContent=error.message;}
  }
  $('plan-goal').onchange=preview;
  $('plan-cancel').onclick=()=>{if(!saving)dialog.close();};dialog.addEventListener('cancel',e=>{if(saving)e.preventDefault();});
  $('plan-transfer-form').onsubmit=async event=>{
    event.preventDefault();if(saving||!selection)return;
    const goal=currentGoal();if(goal?.schools.length&&!$('plan-school').value){$('plan-status').textContent='请先明确这次申请的一所学校；其他学校可分别建立项目。';return;}
    saving=true;$('plan-confirm').disabled=true;$('plan-cancel').disabled=true;
    try{
      const result=await api('/browser-transfer',{kind:selection.kind,item:selection.item,target:selection.kind==='bookmark'?goal:null,school_id:$('plan-school').value,name:$('plan-name').value.trim(),notes:$('plan-notes').value.trim(),todos:goal?selection.data.todos.filter(t=>t.target_id===goal.id):[]});
      $('plan-status').replaceChildren(el('span',result.duplicate?'已有对应项目，本次未覆盖项目和个人进度。':'已建立申请项目，原关注与收藏记录已保留。'),el('br'),link('继续核对目标与材料 →','applications.html?project='+encodeURIComponent(result.project_id)),link('联系与跟进 →','desk.html?project='+encodeURIComponent(result.project_id)));
      await loadOverview();
    }catch(error){$('plan-status').textContent='未完成转换：'+error.message;$('plan-confirm').disabled=false;}
    finally{saving=false;$('plan-cancel').disabled=false;}
  };
  async function loadOverview(){
    if(mode!=='online'||!panel)return;
    try{
      const loaded=await api('');if(mode!=='online'||!OnlineAccount.state.authenticated)return;
      workflow=loaded;panel.hidden=false;list.replaceChildren();
      const projects=Object.values(workflow.projects),today=core.day();
      $('local-overview-status').textContent=projects.length?'正式项目 '+projects.length+' 个 · 以下为账号云端记录':'还没有正式项目。可从下方关注目标或收藏明确建立。';
      for(const p of projects.filter(p=>!['archived','rejected'].includes(p.status)).slice(0,12)){
        const row=el('article'),actions=el('p');row.append(el('strong',p.name));
        const reminders=Object.values(workflow.reminders).filter(r=>r.project_id===p.id&&!r.completed).sort((a,b)=>a.due_date.localeCompare(b.due_date));
        const official=(p.deadlines||[]).filter(d=>d.origin==='policy').sort((a,b)=>a.at.localeCompare(b.at)),next=official.find(d=>d.at.slice(0,10)>=today);
        const materials=Object.values(workflow.materials).filter(m=>m.project_ids.includes(p.id)),targets=Object.values(workflow.targets).filter(t=>t.project_id===p.id);
        const missing=materials.filter(m=>m.missing).length,waiting=targets.filter(t=>t.stage==='waiting').length;
        const stage=({planned:'准备中',submitted:'本人已登记提交',interview:'本人已登记面试',accepted:'本人已登记录取'})[p.status]||p.status;
        row.append(el('p',stage+' · '+materials.length+'份关联材料 · '+targets.length+'位联系目标','start-note'));
        let step=missing?'恢复或更换 '+missing+' 份缺失材料':reminders.length?'个人待办：'+reminders[0].title+' · '+reminders[0].due_date:!p.dept_id?'先明确目标院系、专业和入学年份':!materials.length?'按当前项目要求关联材料':waiting?'已有 '+waiting+' 位导师等待回复，可检查下一次跟进安排':'核对材料清单和下一步联系安排';
        row.append(el('p','下一步：'+step));
        if(reminders.length&&reminders[0].due_date<today){const overdue=el('p','这项个人计划已过期，可在工作台调整；不代表官方报名截止。');overdue.className='personal-due';row.append(overdue);}
        if(next)row.append(el('p','已保存的官方时间：'+next.label+' · '+next.at+'。请到项目页核对最新来源。'));
        else if(official.length)row.append(el('p','已保存的官方时间均已过去，请核对后续公告。'));
        actions.append(link('目标与材料','applications.html?project='+encodeURIComponent(p.id)),link('联系与提醒','desk.html?project='+encodeURIComponent(p.id)));row.append(actions);list.append(row);
      }
      if(projects.length>12)list.append(link('查看全部项目 →','applications.html'));
    }catch(error){if(mode!=='online')return;panel.hidden=false;$('local-overview-status').textContent='申请记录暂不可读：'+error.message;}
  }
  Promise.all([OnlineAccount.ready,CloudLibrary.ready]).then(async()=>{mode=OnlineAccount.state.authenticated?'online':'guest';refresh();await loadOverview();}).catch(()=>{mode='unavailable';refresh();});
  window.PlanTransfer={open,refresh};
})();
