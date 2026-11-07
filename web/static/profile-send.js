'use strict';
// Sending requires live connection and game-scene checks on both client and server.
const profileSend={profileId:null,selected:new Set(),errors:new Map(),sending:false,signature:'',readiness:new Map(),checking:false,checkSequence:0};
function profileSendBlocked(device){
  if(profileSend.checking)return '正在重新检测实例状态…';
  const readiness=profileSend.readiness.get(device.id);
  device={...device,...readiness?.device_state};
  if(device.run.active)return '正在执行配置';
  if(device.account_capture?.active)return '正在采集账号资料';
  if(state.powerPending.has(device.id)||['starting','launching_game','logging_in','stopping'].includes(device.power?.status))return '正在开关机或登录';
  if(state.assigning.has(device.id))return '正在切换任务配置';
  if(device.power?.supported&&!device.power.on)return device.power.status==='stopped'?'未开机':'无法确认开机状态';
  if(!readiness)return profileSend.checking?'正在检查连接和游戏场景':'尚未检查连接和游戏场景';
  return readiness.ready?'':readiness.reason||'实例尚未就绪';
}
function updateProfileSendControls(){
  const available=state.devices.filter(d=>!profileSendBlocked(d));
  const selected=available.filter(d=>profileSend.selected.has(d.id));
  const all=$('#profile-send-all');all.checked=available.length>0&&selected.length===available.length;all.indeterminate=selected.length>0&&selected.length<available.length;all.disabled=profileSend.sending||!available.length;
  $('#profile-send-count').textContent=`已选 ${selected.length} / ${available.length} 个可用实例`;
  const confirm=$('#profile-send-confirm');confirm.disabled=profileSend.sending||!selected.length;confirm.textContent=profileSend.sending?'正在发送…':selected.length?`发送到 ${selected.length} 个实例`:'发送到实例';
  for(const close of $$('#profile-send-dialog [data-close]'))close.disabled=profileSend.sending;
}
function renderProfileSendTargets(){
  const dialog=$('#profile-send-dialog');if(!dialog.open)return;
  const profile=state.profiles.find(p=>p.id===profileSend.profileId);
  if(!profile){if(!profileSend.sending){dialog.close();toast('此方案已不存在，请刷新后重试');}return;}
  $('#profile-send-name').textContent=profile.name;$('#profile-send-task-count').textContent=profile.tasks.length+' 项任务';
  const signature=JSON.stringify([state.devices.map(d=>[d.id,d.name,d.profile_id,d.power?.on,profileSendBlocked(d)]),state.profiles.map(p=>[p.id,p.name]),[...profileSend.errors],profileSend.sending]);
  if(signature===profileSend.signature){updateProfileSendControls();return;}
  profileSend.signature=signature;
  const host=$('#profile-send-targets');const focused=document.activeElement?.closest('.profile-send-target')?.dataset.id;host.replaceChildren();
  if(!state.devices.length)host.append(el('p','还没有实例，请先在模拟器总览添加。','muted'));
  for(const device of state.devices){
    const blocked=profileSendBlocked(device);if(blocked&&!profileSend.sending&&!profileSend.checking)profileSend.selected.delete(device.id);const row=el('label',undefined,'profile-send-target');row.dataset.id=device.id;row.classList.toggle('is-blocked',!!blocked);row.classList.toggle('is-selected',profileSend.selected.has(device.id));
    const check=el('input');check.type='checkbox';check.checked=profileSend.selected.has(device.id);check.disabled=profileSend.sending||!!blocked;check.setAttribute('aria-label','发送到 '+device.name);
    const description=el('span',undefined,'profile-send-target-text');description.append(el('strong',device.name));const current=state.profiles.find(p=>p.id===device.profile_id);description.append(el('small','当前方案：'+(current?.name||'未选择')));
    if(profileSend.errors.has(device.id))description.append(el('small',profileSend.errors.get(device.id),'profile-send-error'));
    const status=el('span',blocked||((device.profile_id===profileSend.profileId)?'已选用此方案':'已连接 · 已进入游戏'),'profile-send-target-state');
    if(blocked)check.setAttribute('aria-description',blocked);
    check.addEventListener('change',()=>{check.checked?profileSend.selected.add(device.id):profileSend.selected.delete(device.id);profileSend.errors.delete(device.id);row.classList.toggle('is-selected',check.checked);updateProfileSendControls();});
    row.append(check,description,status);host.append(row);
  }
  updateProfileSendControls();
  if(focused){const input=$(`[data-id="${CSS.escape(focused)}"] input`,host);if(input&&!input.disabled)input.focus({preventScroll:true});}
}
async function openProfileSend(profileId){
  const opening=++profileSend.checkSequence;
  profileSend.profileId=profileId;profileSend.selected.clear();profileSend.errors.clear();profileSend.sending=false;profileSend.signature='';profileSend.readiness.clear();profileSend.checking=true;
  $('#profile-send-feedback').hidden=true;$('#profile-send-feedback').textContent='';
  if(!$('#profile-send-dialog').open)$('#profile-send-dialog').showModal();
  renderProfileSendTargets();
  try{
    await refresh();
    if(opening!==profileSend.checkSequence||!$('#profile-send-dialog').open)return;
    profileSend.checking=false;
    await refreshProfileSendReadiness();
  }catch(error){
    if(opening!==profileSend.checkSequence||!$('#profile-send-dialog').open)return;
    profileSend.checking=false;profileSend.readiness.clear();profileSend.signature='';renderProfileSendTargets();
    const feedback=$('#profile-send-feedback');feedback.hidden=false;feedback.textContent='刷新实例状态失败：'+error.message;
  }
}
$('#profile-send-all').addEventListener('change',event=>{
  for(const device of state.devices)if(!profileSendBlocked(device)){event.target.checked?profileSend.selected.add(device.id):profileSend.selected.delete(device.id);}
  profileSend.signature='';renderProfileSendTargets();
});
$('#profile-send-dialog').addEventListener('cancel',event=>{if(profileSend.sending)event.preventDefault();});
document.addEventListener('app:data',()=>{if($('#profile-send-dialog').open&&!profileSend.sending)renderProfileSendTargets();});
$('#profile-send-confirm').addEventListener('click',()=>guarded(async()=>{
  if(profileSend.sending)return;
  const profile=state.profiles.find(p=>p.id===profileSend.profileId);if(!profile)throw new Error('方案已不存在');
  const targets=state.devices.filter(d=>profileSend.selected.has(d.id)&&!profileSendBlocked(d));if(!targets.length)return;
  profileSend.sending=true;profileSend.errors.clear();profileSend.signature='';renderProfileSendTargets();
  const feedback=$('#profile-send-feedback');feedback.hidden=false;let sent=0;
  try{
    for(const [index,device] of targets.entries()){
      feedback.textContent=`正在发送到 ${device.name}（${index+1}/${targets.length}）…`;
      state.assigning.add(device.id);
      try{await api('devices/'+device.id+'/receive-profile',{method:'PUT',body:JSON.stringify({profile_id:profile.id})});sent++;profileSend.selected.delete(device.id);}
      catch(error){profileSend.errors.set(device.id,error.message);}
      finally{state.assigning.delete(device.id);}
    }
    try{await refresh();}catch{feedback.textContent='发送请求已处理，但刷新状态失败，请稍后刷新页面确认。';}
    if(sent===targets.length){$('#profile-send-dialog').close();toast(`已将“${profile.name}”发送到 ${sent} 个实例，可在实例卡片点击“启动配置”执行`);}
    else feedback.textContent=`已成功发送 ${sent} / ${targets.length} 个实例；请查看未成功实例的原因，待其就绪后重试。`;
  }finally{profileSend.sending=false;profileSend.signature='';renderProfileSendTargets();updateProfileSendControls();}
}));

async function refreshProfileSendReadiness(){
  if(!$('#profile-send-dialog').open||profileSend.sending||profileSend.checking)return;
  const key=profileSend.profileId,sequence=++profileSend.checkSequence;
  profileSend.checking=true;profileSend.signature='';renderProfileSendTargets();
  try{
    const rows=await api('profiles/'+encodeURIComponent(key)+'/targets',{cache:'no-store'});
    if(sequence!==profileSend.checkSequence||key!==profileSend.profileId||!$('#profile-send-dialog').open)return;
    profileSend.readiness=new Map(rows.map(row=>[row.id,row]));
  }catch(error){
    if(sequence!==profileSend.checkSequence||key!==profileSend.profileId||!$('#profile-send-dialog').open)return;
    profileSend.readiness.clear();const feedback=$('#profile-send-feedback');feedback.hidden=false;feedback.textContent='无法检查实例连接和游戏场景：'+error.message;
  }finally{
    if(sequence===profileSend.checkSequence){profileSend.checking=false;profileSend.signature='';renderProfileSendTargets();}
  }
}
$('#profile-send-dialog').addEventListener('close',()=>{profileSend.checkSequence++;profileSend.checking=false;profileSend.readiness.clear();});
setInterval(()=>{if($('#profile-send-dialog').open&&!document.hidden)refreshProfileSendReadiness();},5000);
