'use strict';
const accountUI={records:[],active:localStorage.getItem('mhxy-account-tab')||'',loading:null,signature:'',sort:{key:'name',dir:1}};
const accountSectionLabels={identity:'角色资料',currency:'角色资产',training:'修炼等级',guild_skills:'帮派技能'};
function accountTime(value){return value?new Date(value).toLocaleString():'尚未采集';}
const ACCOUNT_CAPTURE_SECONDS=60;
function accountCountdown(job){
  if(!job||!job.active||!job.started_at)return null;
  const elapsed=(Date.now()-Date.parse(job.started_at))/1000;
  return Math.max(0,Math.ceil(ACCOUNT_CAPTURE_SECONDS-elapsed));
}
function formatSilver(value){
  if(value==null||!Number.isFinite(Number(value)))return '—';
  const number=Number(value);
  if(Math.abs(number)<100000)return number.toLocaleString();
  const wan=Math.round(number/1000)/10;
  return wan.toLocaleString()+' 万';
}
function formatCurrency(key,value){
  return key==='silver'?formatSilver(value):(value==null?'—':Number(value).toLocaleString());
}
function accountDelta(previous,current,key){
  const before=previous?.[key]?.value,after=current?.[key]?.value;
  if(typeof before!=='number'||typeof after!=='number'||before===after)return null;
  const diff=after-before,up=diff>0;
  const deltaText=key==='silver'?formatSilver(Math.abs(diff)):Math.abs(diff).toLocaleString();
  const span=el('span',(up?'▲ ':'▼ ')+deltaText,'account-delta '+(up?'up':'down'));
  span.title=(up?'较上次采集增加 ':'较上次采集减少 ')+Math.abs(diff).toLocaleString();
  return span;
}
function accountCaptureLabel(job){
  if(!job?.active)return '采集此实例';
  const remaining=accountCountdown(job);
  return remaining>0?'采集中 '+remaining+'s':'即将完成…';
}
function accountValue(value){return value===null||value===undefined||value===''?'—':String(value);}
async function loadAccounts(){
  if(accountUI.loading)return accountUI.loading;
  accountUI.loading=(async()=>{const data=await api('accounts');accountUI.records=data.accounts||[];renderAccounts();})().finally(()=>accountUI.loading=null);
  return accountUI.loading;
}
function selectAccount(id){accountUI.active=id;localStorage.setItem('mhxy-account-tab',id);accountUI.signature='';renderAccounts();}
async function captureAccount(id){
  await post('accounts/'+id+'/capture');await Promise.all([refresh(),loadAccounts()]);
  toast('已开始采集当前游戏窗口，期间请勿手动切换游戏页面');
}
function accountSectionHeader(title,section){
  const heading=el('div',undefined,'account-section-heading');heading.append(el('h2',title));
  if(section)heading.append(el('small',accountTime(section.updated_at),'muted'));
  return heading;
}
function accountSkills(kind,section){
  const card=el('section',undefined,'account-section');card.append(accountSectionHeader(accountSectionLabels[kind],section));
  if(section?.error)card.append(el('p','本次读取失败，以下为上次记录：'+section.error,'account-warning'));
  const skills=section?.data?.skills||[];
  if(!skills.length){
    const empty=el('div',undefined,'account-section-empty');
    empty.append(el('span',section?.status==='unavailable'?'当前不可采集':section?'未识别到等级':'尚未采集','account-empty-label'),
      el('p',section?.message||'采集运行中的游戏窗口后，在这里查看等级。','muted'));card.append(empty);
  }else{
    const list=el('div',undefined,'account-skill-list');
    for(const skill of skills){
      const row=el('div',undefined,'account-skill-row'),name=el('div');name.append(el('strong',skill.name));
      if(skill.group)name.append(el('small',skill.group,'muted'));
      row.append(name,el('span',skill.level+(skill.maximum!=null?' / '+skill.maximum:' 级'),'account-skill-level'));list.append(row);
    }
    card.append(list);
    if(section?.message)card.append(el('p',section.message,'account-section-note'));
  }
  return card;
}
function accountRow(device){
  const record=accountUI.records.find(item=>item.device_id===device.id)||{};
  const identity=record.sections?.identity?.data||{},currency=record.sections?.currency?.data||{};
  const capture=record.capture||{};
  return {device,record,identity,currency,
    name:device.name||'',role:identity.role_name||'',school:identity.school||'',
    level:identity.level??null,gold:currency.gold?.value??null,silver:currency.silver?.value??null,
    vitality:identity.vitality??null,vitality_max:identity.vitality_max??null,
    score:currency.score??null,
    updated:record.updated_at||''};
}
function accountSortValue(row,key){
  switch(key){
    case 'name':return row.name;case 'role':return row.role;case 'school':return row.school;
    case 'level':return row.level??-1;case 'gold':return row.gold??-1;case 'silver':return row.silver??-1;
    case 'vitality':return row.vitality??-1;case 'score':return row.score??-1;
    case 'updated':return row.updated||'';default:return '';
  }
}
function renderAccountOverview(devices){
  const host=$('#account-overview');if(!host)return;
  const rows=devices.map(accountRow);
  const sort=accountUI.sort;
  rows.sort((a,b)=>{
    const left=accountSortValue(a,sort.key),right=accountSortValue(b,sort.key);
    if(typeof left==='number'&&typeof right==='number')return (left-right)*sort.dir;
    return String(left).localeCompare(String(right),'zh')*sort.dir;
  });
  host.replaceChildren();
  const collected=rows.filter(row=>row.record.updated_at).length;
  host.append(el('p','共 '+rows.length+' 个实例 · 已采集 '+collected+' 个','account-overview-note'));
  const table=el('table',undefined,'account-table');
  const head=el('thead'),headRow=el('tr');
  const columns=[['name','实例'],['role','角色'],['school','门派'],['level','等级'],['gold','金币'],['silver','银币'],['vitality','活力'],['score','人物评分'],['updated','最后采集']];
  const numericColumns=new Set(['level','gold','silver','vitality','score']);
  for(const [key,label] of columns){
    const th=el('th',label,key===sort.key?'sorted':'');
    if(numericColumns.has(key))th.classList.add('num');
    if(key===sort.key)th.append(el('span',sort.dir>0?' ▲':' ▼','sort-arrow'));
    th.addEventListener('click',()=>{
      if(accountUI.sort.key===key)accountUI.sort.dir*=-1;else accountUI.sort={key,dir:1};
      accountUI.signature='';renderAccounts();
    });
    headRow.append(th);
  }
  head.append(headRow);table.append(head);
  const body=el('tbody');
  for(const row of rows){
    const tr=el('tr',undefined,row.device.id===accountUI.active?'active':'');
    tr.dataset.id=row.device.id;
    tr.append(el('td',row.name),el('td',row.role||'—',row.role?'':'muted-cell'),el('td',row.school||'—',row.school?'':'muted-cell'));
    tr.append(el('td',row.level!=null?row.level+' 级':'—','num'+(row.level!=null?'':' muted-cell')));
    tr.append(el('td',row.gold!=null?Number(row.gold).toLocaleString():'—','num'+(row.gold!=null?'':' muted-cell')));
    tr.append(el('td',formatSilver(row.silver),'num'+(row.silver!=null?'':' muted-cell')));
    tr.append(el('td',row.vitality!=null?row.vitality+(row.vitality_max!=null?' / '+row.vitality_max:''):'—','num'+(row.vitality!=null?'':' muted-cell')));
    tr.append(el('td',row.score!=null?Number(row.score).toLocaleString():'—','num'+(row.score!=null?'':' muted-cell')));
    tr.append(el('td',row.updated?accountTime(row.updated):'从未采集',row.updated?'':'muted-cell'));
    tr.addEventListener('click',()=>selectAccount(row.device.id));
    body.append(tr);
  }
  table.append(body);
  const totals=rows.reduce((acc,row)=>{
    if(typeof row.gold==='number'){acc.gold+=row.gold;acc.goldCount+=1;}
    if(typeof row.silver==='number'){acc.silver+=row.silver;acc.silverCount+=1;}
    return acc;
  },{gold:0,silver:0,goldCount:0,silverCount:0});
  const foot=el('tfoot'),totalRow=el('tr',undefined,'account-total');
  totalRow.append(el('td','合计'));
  totalRow.append(el('td','—','muted-cell'));
  totalRow.append(el('td','—','muted-cell'));
  totalRow.append(el('td','—','muted-cell num'));
  totalRow.append(el('td',totals.goldCount?totals.gold.toLocaleString():'—',totals.goldCount?'num':'muted-cell'));
  totalRow.append(el('td',totals.silverCount?formatSilver(totals.silver):'—',totals.silverCount?'num':'muted-cell'));
  totalRow.append(el('td','—','muted-cell num'));
  totalRow.append(el('td','—','muted-cell num'));
  totalRow.append(el('td','—','muted-cell'));
  foot.append(totalRow);table.append(foot);
  host.append(table);
}
function renderAccounts(){
  if(state.view!=='accounts')return;
  const devices=state.devices;
  if(!devices.some(d=>d.id===accountUI.active))accountUI.active=devices.find(d=>d.power?.on)?.id||devices[0]?.id||'';
  $('#account-count').textContent=devices.length;$('#accounts-empty').hidden=devices.length>0;
  const signature=JSON.stringify({devices:devices.map(d=>[d.id,d.name,d.power?.on,d.run.active,d.account_capture?.active]),records:accountUI.records,active:accountUI.active,sort:accountUI.sort});
  if(signature===accountUI.signature)return;accountUI.signature=signature;
  renderAccountOverview(devices);
  const tabs=$('#account-tabs');tabs.replaceChildren();
  for(const device of devices){
    const tab=button('','account-tab'+(device.id===accountUI.active?' active':''),()=>selectAccount(device.id));
    tab.setAttribute('role','tab');tab.setAttribute('aria-selected',String(device.id===accountUI.active));tab.setAttribute('aria-controls','account-panel');
    const dot=el('span',undefined,'account-tab-dot'+(device.power?.on?' online':''));
    tab.append(dot,el('span',device.name));
    const job=accountUI.records.find(record=>record.device_id===device.id)?.capture;
    if(job?.active)tab.append(el('small','采集中'));
    tabs.append(tab);
  }
  const host=$('#account-panel');host.replaceChildren();
  const device=devices.find(d=>d.id===accountUI.active);if(!device)return;
  const record=accountUI.records.find(record=>record.device_id===device.id)||{sections:{},capture:{}};
  const sections=record.sections||{},identity=sections.identity?.data||{},currency=sections.currency?.data||{},job=record.capture||{};
  const heading=el('section',undefined,'account-role-card'),role=el('div',undefined,'account-role-identity');
  const avatar=el('div',undefined,'account-avatar');
  if(record.avatar_at){
    const portrait=el('img');portrait.alt=identity.role_name||device.name;
    portrait.src='/avatar/'+encodeURIComponent(device.id)+'.png?v='+encodeURIComponent(record.avatar_at);
    portrait.addEventListener('error',()=>{portrait.remove();avatar.textContent=identity.school?.slice(0,1)||'角';});
    avatar.append(portrait);
  }else avatar.textContent=identity.school?.slice(0,1)||'角';
  const title=el('div');title.append(el('p',device.name+' · '+(device.power?.on?'窗口运行中':'窗口未运行'),'account-role-device'),
    el('h2',identity.role_name||'等待采集角色资料'));
  const tags=el('div',undefined,'account-role-tags');
  for(const text of [identity.school,identity.level!=null?identity.level+' 级':null,identity.role_id?'ID '+identity.role_id:null])if(text)tags.append(el('span',text));
  title.append(tags);role.append(avatar,title);
  const controls=el('div',undefined,'account-role-controls');
  const capture=button(accountCaptureLabel(job),'primary',()=>captureAccount(device.id));
  capture.disabled=!!job.active||!!device.run.active||!device.power?.on;
  const note=job.active?job.phase:device.run.active?'实例任务运行中，结束后可采集':!device.power?.on?'打开游戏后可采集；历史数据继续保留':'采集会读取游戏页面，结束后返回主界面';
  controls.append(capture,el('small',note,'muted'));heading.append(role,controls);host.append(heading);
  if(job.active||job.status==='failed'||job.status==='partial'){
    const progress=el('div',undefined,'account-capture-status'+(job.status==='failed'?' failed':''));
    progress.setAttribute('role','status');progress.append(el('span',job.active?'◌':'ⓘ'),el('span',job.phase||'采集未完成'));host.append(progress);
  }
  const metrics=el('div',undefined,'account-currency-grid');
  for(const [key,label,cls] of [['gold','金币','gold'],['silver','银币','silver']]){
    const value=currency[key],metric=el('section',undefined,'account-currency '+cls);
    const line=el('div',undefined,'account-currency-value');
    const strong=el('strong',value?.value!=null?(value.approximate?'约 ':'')+formatCurrency(key,value.value):'—');
    if(value?.value!=null)strong.title=Number(value.value).toLocaleString();
    line.append(strong);
    const change=accountDelta(sections.currency?.previous?.data,currency,key);
    if(change)line.append(change);
    metric.append(el('p',label),line,
      el('small',value?.value!=null?'采集于 '+accountTime(sections.currency?.updated_at):'尚未识别'));
    metrics.append(metric);
  }
  host.append(metrics);
  if(sections.currency?.error)host.append(el('p','余额保留上次记录：'+sections.currency.error,'account-warning'));
  const facts=el('section',undefined,'account-section account-facts');facts.append(accountSectionHeader('角色资料',sections.identity));
  const grid=el('dl',undefined,'account-fact-grid');
  for(const [label,value] of [['角色名称',identity.role_name],['门派',identity.school],['等级',identity.level],
      ['人物评分',currency.score!=null?Number(currency.score).toLocaleString():null],['帮派贡献',identity.guild_contribution],
      ['活力',identity.vitality!=null?identity.vitality+' / '+accountValue(identity.vitality_max):null],
      ['帮派',identity.guild_name]]){
    const item=el('div');item.append(el('dt',label),el('dd',accountValue(value)));grid.append(item);
  }
  facts.append(grid);if(sections.identity?.message)facts.append(el('p',sections.identity.message,'account-section-note'));host.append(facts);
  const skills=el('div',undefined,'account-development-grid');skills.append(accountSkills('training',sections.training),accountSkills('guild_skills',sections.guild_skills));host.append(skills);
  host.append(el('p','“—”表示尚未采集或未识别；等级与余额均来自游戏画面。最后采集：'+accountTime(record.updated_at),'account-data-note'));
  $('#capture-running-accounts').disabled=!devices.some(d=>d.power?.on&&!d.run.active&&!d.account_capture?.active);
}
$('#capture-running-accounts').addEventListener('click',()=>guarded(async()=>{
  const response=await post('accounts/capture-running');const result=response.results||[];
  await Promise.all([refresh(),loadAccounts()]);
  toast(result.length?`已安排 ${result.filter(item=>item.ok).length} 个运行窗口采集`+(result.some(item=>!item.ok)?'，忙碌实例已跳过':''):'没有可采集的运行窗口');
}));

setInterval(()=>{
  if(state.view!=='accounts')return;
  const record=accountUI.records.find(item=>item.device_id===accountUI.active&&item.capture?.active);
  if(!record)return;
  const target=document.querySelector('.account-role-controls button.primary');
  if(!target)return;
  const label=accountCaptureLabel(record.capture);
  if(target.textContent!==label)target.textContent=label;
},1000);
