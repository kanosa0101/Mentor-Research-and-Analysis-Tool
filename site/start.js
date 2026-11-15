(function(){
  'use strict';
  const core=window.BrowserLibraryCore,$=id=>document.getElementById(id),today=core.day();
  const [calendarYear,month]=today.split('-').map(Number),defaults={exam:calendarYear+(month>=9?1:0),recommend:calendarYear+(month>=11?2:1)};
  const schoolMap=new Map((window.SCHOOL_CATALOG?.units||window.ADMISSIONS_DATA?.units||[]).map(u=>[u.school,{id:u.school,name:u.school_name}]));
  const schools=[...schoolMap.values()].sort((a,b)=>a.name.localeCompare(b.name,'zh-CN'));
  let selectedSchools=new Map(),activeTab='bookmarks',pendingImport=null,restoring=true;
  const label=target=>target.path==='exam'?target.year+' 年入学统考':target.year+' 届本科生保研准备';
  const element=(tag,text,className)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;};
  const button=(text,action)=>{const node=element('button',text);node.type='button';node.onclick=action;return node;};
  const status=(text,error=false)=>{$('library-status').textContent=text;$('library-status').style.color=error?'#9a4e12':'';};
  function commit(action,message){try{const next=action(core.read(localStorage));core.write(localStorage,next);renderLibrary();status(message);window.dispatchEvent(new CustomEvent('browser-library-change'));return true;}catch(error){status('未保存：'+error.message,true);return false;}}
  function draft(){
    const path=document.querySelector('[name="path"]:checked').value,year=Number($('target-year').value);
    if(!Number.isInteger(year)||year<2000||year>2100)throw new Error('请填写有效的年份');
    return {path,year,schools:[...selectedSchools.values()],interest:$('target-interest').value.trim()};
  }
  function selectTab(name){activeTab=name;for(const key of ['targets','bookmarks','todos']){$('panel-'+key).hidden=key!==name;$('tab-'+key).setAttribute('aria-selected',String(key===name));}}
  function addTodo(title,targetId=''){
    const saved=commit(data=>{data.todos.push({id:core.id('todo'),title:title.slice(0,300),done:false,due_date:'',target_id:targetId,created_at:today});return data;},'已添加待办，仅保存在此浏览器。');
    if(saved)selectTab('todos');
  }
  function schoolPicker(){
    const q=$('start-school-search').value.trim().toLowerCase(),list=$('start-school-options');list.replaceChildren();
    const matching=schools.filter(s=>(s.id+' '+s.name).toLowerCase().includes(q));
    for(const school of matching){const line=element('label'),input=document.createElement('input');input.type='checkbox';input.value=school.id;input.checked=selectedSchools.has(school.id);input.onchange=()=>{if(input.checked){if(selectedSchools.size>=20){input.checked=false;$('target-status').textContent='每个关注目标最多选择20所学校。';return;}selectedSchools.set(school.id,school);}else selectedSchools.delete(school.id);selection();plan();};line.append(input,element('span',school.name));list.append(line);}
    $('school-search-status').textContent=matching.length+' 所可选学校'+(schools.length?'':'；学校目录暂不可用，可先跨校探索。');selection();
  }
  function selection(){
    $('school-selection-label').textContent=selectedSchools.size?'学校 · 已选 '+selectedSchools.size+' 所（可继续搜索多选）':'学校（可多选，未选择时跨校探索）';
    const chips=$('target-school-chips');chips.replaceChildren();
    for(const school of selectedSchools.values())chips.append(button(school.name+' ×',()=>{selectedSchools.delete(school.id);schoolPicker();plan();}));
  }
  function links(target,school){
    const base={};if(school)base.school=school.id;
    const degree={...base,degree:'master',route:target.path};if(target.path==='exam')degree.year=String(target.year);
    const qs=values=>new URLSearchParams(values).toString();
    const opportunity={};if(school)opportunity.school=school.name;if(target.path==='recommend')opportunity.year=String(target.year);
    const topics=target.interest.split(/[,，、;；]+/).map(value=>value.trim()).filter(Boolean);
    if(topics.length===1)opportunity.query=topics[0];
    const notice={...base,notice_cycle:'current'};if(target.path==='exam'){notice.notice_route='exam';notice.notice_admission_year=String(target.year);}
    return [
      ['按兴趣找导师','discovery.html?'+qs({...degree,...(topics.length?{topics:topics.join(',')}: {})})],
      ['学校与招生要求','admissions.html?'+qs(degree)],
      ['招生通知与进程','notices.html?'+qs(notice)],
      [target.path==='recommend'?'冬令营与科研机会':'科研与营活动（另核届别）','opportunities.html?'+qs(opportunity)],
    ];
  }
  function plan(){
    let target;try{target=draft();}catch(error){$('target-status').textContent=error.message;$('current-actions').replaceChildren();$('target-entries').replaceChildren(element('p','请先填写有效年份，再查看相应入口。'));return;}
    if(!restoring)try{sessionStorage.setItem('mentor-start-draft-v1',JSON.stringify(target));}catch(error){}
    $('target-status').textContent='';
    $('target-year-label').textContent=target.path==='exam'?'计划研究生入学年份':'本人本科毕业届别';
    $('path-context').textContent='按 '+today+' 的日历周期整理 · '+label(target)+'。'+(target.path==='exam'?'先确认本人报考和确认状态，再查考试安排与后续通知；这里不会显示为已报名或已具备资格。':'先向本校核实推免资格；再核对目标院校要求。毕业届别不自动填成研究生入学年，活动是否适用于你以官方说明为准。');
    const actions=target.path==='exam'?[
      ['核对报考专业与考试科目','查看目标学校和院系要求，确认专业代码、科目与个人报考条件。'],
      ['确认网报、网上确认与补正状态','关注资格审核、材料补正和考试安排；不能只看是否发布过报名通知。'],
      ['整理当前阶段的材料与考试计划','依据对应项目的官方清单准备，不把个人计划日期当作官方截止。'],
    ]:[
      ['向本校确认推免资格要求','本校资格、成绩排名及推荐规则，需要向本校教务或院系核实。'],
      ['筛选研究方向相符的导师与院系','先看方向和官方联系方式，了解研究内容后再准备有针对性的联系。'],
      ['核对冬令营或科研实践的面向人群','确认年级、学校范围、材料与报名窗口；资料待核验不代表可以报名。'],
      ['按目标项目官方清单准备材料','整理研究经历与个人资料；实际材料要求以每个机会的官方清单为准。'],
    ];
    const list=$('current-actions');list.replaceChildren();
    for(const [title,note] of actions){const row=element('div',undefined,'start-step'),body=element('div');body.append(element('strong',title),element('p',note,'start-note'));row.append(body,button('加入我的待办',()=>addTodo(title)));list.append(row);}
    const entries=$('target-entries');entries.replaceChildren();
    for(const school of target.schools.length?target.schools:[null]){const row=element('div',undefined,'entry-school'),actions=element('div',undefined,'start-actions');row.append(element('h3',school?.name||'跨校探索'));for(const [title,url] of links(target,school)){const a=element('a',title);a.href=core.safeUrl(url);actions.append(a);}row.append(actions);entries.append(row);}
    if(target.interest.split(/[,，、;；]+/).filter(value=>value.trim()).length>1)entries.append(element('p','多个兴趣在导师页按任一关键词查找；机会页先保留所选学校的全部线索，可再用一个方向关键词细查。','start-note'));
  }
  function renderLibrary(){
    let data;try{data=core.read(localStorage);}catch(error){status('浏览器记录暂不可读取：'+error.message+'。未覆盖原有记录。',true);return;}
    for(const [key,title] of [['targets','关注目标'],['bookmarks','收藏'],['todos','待办']])$('tab-'+key).textContent=title+' '+data[key].length;
    const targetPanel=$('panel-targets');targetPanel.replaceChildren();
    for(const target of data.targets){const row=element('div',undefined,'library-item'),actions=element('div',undefined,'start-actions');row.dataset.planKind='target';row.dataset.planId=target.id;row.append(element('strong',label(target)),element('p',[target.schools.map(s=>s.name).join('、')||'跨校探索',target.interest].filter(Boolean).join(' · '),'start-note'));actions.append(button('应用此目标',()=>{document.querySelector('[name="path"][value="'+target.path+'"]').checked=true;$('target-year').value=target.year;$('target-interest').value=target.interest;selectedSchools=new Map(target.schools.map(s=>[s.id,s]));schoolPicker();plan();$('target-form').scrollIntoView({block:'start'});$('target-status').textContent='已应用保存的关注目标；更改后可另存新目标。';}),button('删除目标',()=>commit(data=>core.remove(data,'targets',target.id),'已删除关注目标；关联待办保留为独立待办。')));row.append(actions);targetPanel.append(row);}
    if(!data.targets.length)targetPanel.append(element('p','尚无关注目标。在上方选择路径、学校和兴趣后，点击“保存为关注目标”。','start-note'));
    const bookmarkPanel=$('panel-bookmarks');bookmarkPanel.replaceChildren();
    for(const item of data.bookmarks){const row=element('div',undefined,'library-item'),a=element('a',item.title),actions=element('div',undefined,'start-actions');a.href=core.safeUrl(item.url);row.dataset.planKind='bookmark';row.dataset.planId=item.id;row.append(element('p',({mentor:'导师',notice:'招生通知',opportunity:'保研 / 科研机会'})[item.kind]+' · 收藏于 '+item.created_at,'start-note'),a);actions.append(button('添加跟进待办',()=>addTodo('查看并核对：'+item.title)),button('删除收藏',()=>commit(data=>core.remove(data,'bookmarks',item.id),'已删除此浏览器中的收藏。')));row.append(actions);bookmarkPanel.append(row);}
    if(!data.bookmarks.length){const empty=element('p','尚无收藏。在导师、招生通知或机会卡片上点击“收藏到此浏览器”，再回到这里。','start-note');bookmarkPanel.append(empty);}
    const targetSelect=$('todo-target'),previous=targetSelect.value;targetSelect.replaceChildren(new Option('不关联',''));for(const target of data.targets)targetSelect.add(new Option(label(target)+(target.schools.length?' · '+target.schools.map(s=>s.name).join('、'):''),target.id));targetSelect.value=data.targets.some(t=>t.id===previous)?previous:'';
    const todos=$('todo-list');todos.replaceChildren();
    for(const item of [...data.todos].sort((a,b)=>Number(a.done)-Number(b.done)||(a.due_date||'9999').localeCompare(b.due_date||'9999'))){
      const row=element('div',undefined,'library-item'+(item.done?' todo-done':'')),line=element('label',undefined,'todo-title'),input=document.createElement('input');input.type='checkbox';input.checked=item.done;input.onchange=()=>{if(!commit(data=>{data.todos.find(t=>t.id===item.id).done=input.checked;return data;},input.checked?'已标记完成。':'已恢复为待办。'))input.checked=item.done;};line.append(input,element('span',item.title,'todo-text'));row.append(line);
      const target=data.targets.find(t=>t.id===item.target_id),notes=[item.due_date?'个人计划 '+item.due_date:'',target?label(target):''].filter(Boolean);if(notes.length)row.append(element('p',notes.join(' · ')+(item.due_date&&item.due_date<today&&!item.done?' · 已过个人计划日期':''),'start-note'+(item.due_date&&item.due_date<today&&!item.done?' due-overdue':'')));
      row.append(button('删除待办',()=>commit(data=>core.remove(data,'todos',item.id),'已删除待办。')));todos.append(row);
    }
    if(!data.todos.length)todos.append(element('p','还没有待办。可以直接填写，或把上方当前行动加入待办。','start-note'));
    selectTab(activeTab);window.PlanTransfer?.refresh();
  }
  $('exam-path-title').textContent=defaults.exam+' 年入学统考';$('recommend-path-title').textContent=defaults.recommend+' 届本科生保研准备';$('target-year').value=defaults.recommend;
  for(const input of document.querySelectorAll('[name="path"]'))input.onchange=()=>{$('target-year').value=defaults[input.value];plan();};
  $('target-year').oninput=plan;$('target-interest').oninput=plan;$('start-school-search').oninput=schoolPicker;
  $('clear-target-schools').onclick=()=>{selectedSchools.clear();schoolPicker();plan();};
  $('target-form').onsubmit=event=>{event.preventDefault();let target;try{target=draft();}catch(error){$('target-status').textContent=error.message;return;}let duplicate=false;
    const saved=commit(data=>{duplicate=data.targets.some(t=>t.path===target.path&&t.year===target.year&&t.interest===target.interest&&JSON.stringify(t.schools.map(s=>s.id).sort())===JSON.stringify(target.schools.map(s=>s.id).sort()));if(!duplicate)data.targets.push({...target,id:core.id('target'),created_at:today});return data;},'关注目标已保存在此浏览器。');
    if(saved){$('target-status').textContent=duplicate?'相同目标已保存，可在下方“关注目标”查看。':'已保存关注目标。没有创建正式申请或提交报名。';selectTab('targets');}
  };
  $('todo-form').onsubmit=event=>{event.preventDefault();const title=$('todo-title').value.trim();if(!title){status('请填写要做的事。',true);return;}if(commit(data=>{data.todos.push({id:core.id('todo'),title,done:false,due_date:$('todo-date').value,target_id:$('todo-target').value,created_at:today});return data;},'待办已保存在此浏览器。')){$('todo-title').value='';$('todo-date').value='';}};
  const tabs=[...document.querySelectorAll('[data-library-tab]')];
  for(const tab of tabs){tab.onclick=()=>selectTab(tab.dataset.libraryTab);tab.onkeydown=event=>{if(!['ArrowRight','ArrowLeft','Home','End'].includes(event.key))return;event.preventDefault();const index=event.key==='Home'?0:event.key==='End'?tabs.length-1:(tabs.indexOf(tab)+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[index].click();tabs[index].focus();};}
  $('library-export').onclick=()=>{try{const data=core.read(localStorage),url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})),a=element('a');a.href=url;a.download='browser-application-library-'+today+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);status('已生成浏览器备份，请妥善保存下载的文件。');}catch(error){status('导出失败：'+error.message,true);}};
  $('library-import-open').onclick=()=>$('library-import').click();
  $('library-import').onchange=async()=>{pendingImport=null;$('import-preview').hidden=true;const file=$('library-import').files[0];if(!file)return;try{if(file.size>2000000)throw new Error('备份文件不能超过2MB');pendingImport=core.parse(await file.text());$('import-summary').textContent='检查通过：'+pendingImport.targets.length+' 个关注目标、'+pendingImport.bookmarks.length+' 条收藏、'+pendingImport.todos.length+' 条待办。尚未写入，确认后合并新增条目。';$('import-preview').hidden=false;}catch(error){status('未导入：'+error.message,true);}finally{$('library-import').value='';}};
  $('library-import-cancel').onclick=()=>{pendingImport=null;$('import-preview').hidden=true;status('已取消导入，记录未改变。');};
  $('library-import-confirm').onclick=()=>{if(!pendingImport)return;if(commit(data=>core.merge(data,pendingImport),'已合并备份中的新增条目，原有记录保持不变。')){pendingImport=null;$('import-preview').hidden=true;}};
  window.addEventListener('storage',event=>{if(event.key===core.KEY)renderLibrary();});
  try{const saved=JSON.parse(sessionStorage.getItem('mentor-start-draft-v1')||'null');if(saved&&['exam','recommend'].includes(saved.path)&&Number.isInteger(saved.year)&&saved.year>=2000&&saved.year<=2100&&typeof saved.interest==='string'&&saved.interest.length<=200&&Array.isArray(saved.schools)){document.querySelector('[name="path"][value="'+saved.path+'"]').checked=true;$('target-year').value=saved.year;$('target-interest').value=saved.interest;selectedSchools=new Map(saved.schools.filter(s=>schoolMap.has(s.id)).map(s=>[s.id,schoolMap.get(s.id)]));}}catch(error){}
  schoolPicker();plan();renderLibrary();restoring=false;window.START_READY=true;
})();
