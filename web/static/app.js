const emulatorSpec = d => d.emulator || d.mumu;
const sameEmulator = (a,b) => { const x=emulatorSpec(a), y=emulatorSpec(b); return x && y && (x.kind || 'mumu') === (y.kind || 'mumu') && x.index === y.index && x.app_path === y.app_path; };
'use strict';
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const MAX_DEVICES = 10;
const state = {token: sessionStorage.getItem('mhxy-token') || '', devices: [], catalog: null, selected: new Set(), filter: 'all', edit: null, queue: [], logId: null, screenId: null, screenURL: null, deleting: null, pollBusy: false, mumuRows: [], profiles: [], view: 'devices', editingProfile: null, bindDeviceId: null, pickedTasks: new Set(), assigning: new Set(), profilesSignature: '', deletingProfile: null, settingsId: null, powerPending: new Map(), authRequired: true, openTaskCategories: new Set(['个人日常']), collapsedSearchCategories: new Set()};
const labels = {idle:'待运行',starting:'连接中',running:'运行中',stopping:'停止中',stopped:'已停止',completed:'已完成',ready:'游戏已打开',failed:'异常'};
function el(tag, text, cls) { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; }
function button(text, cls, action) { const b = el('button', text, cls); b.type = 'button'; b.addEventListener('click', () => guarded(action)); return b; }
async function guarded(fn) { try { return await fn(); } catch (err) { toast(err.message); } }
let toastTimer;
function toast(message) { $('#toast').textContent = message; $('#toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').hidden = true, 6500); }
async function api(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch('/api/' + path, {...options, signal: options.signal || controller.signal, headers: {...(state.token?{'Authorization':'Bearer ' + state.token}:{}),'Content-Type':'application/json', ...options.headers}});
    if (response.status === 401) { logout(); throw new Error('访问令牌无效，请重新连接'); }
    if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(typeof body.detail === 'string' ? body.detail : '请求失败，请检查输入参数'); }
    return options.binary ? response.blob() : response.json();
  } finally { clearTimeout(timer); }
}
const post = (path, body = {}) => api(path, {method:'POST', body:JSON.stringify(body)});
function logout() { pauseMonitorStreams(); state.token = ''; sessionStorage.removeItem('mhxy-token'); $('#shell').hidden = true; $('#login').hidden = false; $$('dialog[open]').forEach(d => d.close()); }
async function connect() {
  state.catalog = await api('catalog'); await refresh(); await loadVersion();
  $('#login').hidden = true; $('#shell').hidden = false;
  $('#nav-monitor').hidden = !state.monitorAllowed;
  if(state.authRequired)sessionStorage.setItem('mhxy-token',state.token);else sessionStorage.removeItem('mhxy-token');
  if(!sessionStorage.getItem('mhxy-update-checked') && $('#auto-update').checked){
    sessionStorage.setItem('mhxy-update-checked','1'); guarded(()=>checkUpdate(true));
  }
}
$('#login-form').addEventListener('submit', async e => { e.preventDefault(); const b = $('button', e.target); b.disabled = true; state.token = $('#token').value.trim(); try { await connect(); $('#token').value = ''; } catch (err) { $('#login-error').textContent = err.message; } finally { b.disabled = false; } });
$('#logout').addEventListener('click', logout);
$$('[data-close]').forEach(b => b.addEventListener('click', () => document.getElementById(b.dataset.close).close()));
async function refresh() {
  [state.devices, state.profiles] = await Promise.all([api('devices'), api('profiles')]);
  for (const id of state.selected) if (!state.devices.some(d => d.id === id)) state.selected.delete(id);
  render(); renderProfiles(); if(state.view==='monitor')renderMonitors();
  if(state.view==='activity') await loadActivity();
  if(state.view==='accounts') await loadAccounts();
  $('#connection').textContent = '已连接';
  document.dispatchEvent(new CustomEvent('app:data'));
}
function visibleDevices() { const search = $('#search').value.toLowerCase(); return state.devices.filter(d => (d.name + d.address).toLowerCase().includes(search) && (state.filter === 'all' || (state.filter === 'running' ? d.run.active : d.run.status === 'failed'))); }
function render() {
  $('#total').textContent = state.devices.length; $('#device-count').textContent = state.devices.length + ' / ' + MAX_DEVICES;
  const totalHint = $('#total-hint'); if (totalHint) totalHint.textContent = '最高上限 ' + MAX_DEVICES + ' 个实例';
  $('#running').textContent = state.devices.filter(d => d.run.active).length;
  $('#completed').textContent = state.devices.filter(d => d.run.status === 'completed').length;
  $('#failed').textContent = state.devices.filter(d => d.run.status === 'failed').length;
  $('#empty').hidden = state.devices.length > 0;
  const list = visibleDevices(); $('#no-results').hidden = state.devices.length === 0 || list.length > 0;
  const host = $('#devices');
  // Update existing cards in place so a periodic refresh does not steal focus.
  const wanted = new Set(list.map(d => d.id));
  for (const card of [...host.children]) if (!wanted.has(card.dataset.id)) card.remove();
  for (const d of list) {
    let card = [...host.children].find(c => c.dataset.id === d.id);
    if (!card) {
      card = el('article', undefined, 'device-card'); card.dataset.id = d.id;
      card.innerHTML = '<div class="card-head"><input type="checkbox"><div class="card-title"><div class="card-title-row"><h2></h2><span class="instance-activity" role="img"><svg class="instance-activity-person" viewBox="0 0 52 36" width="52" height="36" aria-hidden="true" focusable="false"><g class="activity-runner"><path class="runner-ground" d="M7 33h9m8 0h8m7 0h5"/><g class="runner-body"><g class="runner-arm runner-arm-back"><path d="M26 14l7 5 5-4"/></g><g class="runner-leg runner-leg-back"><path d="M23 23l7 4-3 5"/></g><g class="runner-leg runner-leg-front"><path d="M23 23l-6 7-7 1"/></g><path class="runner-shirt" d="M24 12q-5 0-6 9l7 4 5-9z"/><g class="runner-arm runner-arm-front"><path d="M24 15l-6 5-5-3"/></g><g class="runner-head"><circle cx="28" cy="7" r="5"/><path class="person-hair" d="M23 7a5 5 0 0 1 10-1l-4-2-2 3z"/><path class="person-face" d="M30 7h.1m-1 3 2-.5"/></g></g><path class="runner-speed" d="M6 12h7m-9 5h6m-2 5h5"/></g><g class="activity-sleeper"><path class="sleep-ground" d="M5 32h40"/><rect class="sleep-pillow" x="5" y="25" width="17" height="7" rx="3"/><g class="sleep-breath"><path class="sleep-blanket" d="M19 30v-9q10-8 19 1l5 8z"/><path class="sleep-blanket-fold" d="M23 20q3 3 2 9"/><g class="sleep-head"><circle cx="14" cy="23" r="6"/><path class="person-hair" d="M8 23a6 6 0 0 1 10-5l-5 1-1 4z"/><path class="person-face" d="M14 23q1 1 2 0m1 3h1"/></g></g><text class="sleep-z sleep-z-one" x="24" y="15">z</text><text class="sleep-z sleep-z-two" x="32" y="11">Z</text><text class="sleep-z sleep-z-three" x="41" y="7">Z</text></g></svg><span class="instance-activity-label" aria-hidden="true"></span></span></div><p></p></div><label class="power-control"><span></span><input type="checkbox" role="switch"><i></i></label></div><div class="card-body"><div class="task-line"><span></span><small></small></div><div class="progress"><i></i></div><div class="card-meta"><span></span><span></span></div><div class="task-detail"></div><div class="sub-progress"><i></i></div><div class="task-phase"></div></div><div class="card-actions"></div>';
      $('.card-head>input', card).addEventListener('change', e => { e.target.checked ? state.selected.add(d.id) : state.selected.delete(d.id); render(); });
      const settings = button('⚙','icon-button device-settings-button',() => openDeviceSettings(d.id)); settings.setAttribute('aria-label','实例设置'); settings.title = '实例名称'; $('.card-head',card).append(settings);
      $('.power-control input',card).addEventListener('change',e=>guarded(()=>setDevicePower(d.id,e.target.checked)));
      const profileLabel = el('label','任务配置','card-profile');
      const select = el('select'); select.setAttribute('aria-label',d.name + '的任务配置');
      select.addEventListener('change',() => guarded(() => assignDeviceProfile(d.id,select.value || null)));
      profileLabel.append(select); $('.card-body',card).after(profileLabel);
      const actions = $('.card-actions', card);
      actions.append(button('▷ 启动', 'primary run-button', async () => { await post('devices/' + d.id + '/start'); await refresh(); }));
      actions.append(button('配置', 'secondary config-button', () => openConfig(d.id)));
      actions.append(button('日志', 'subtle', () => openLogs(d.id)));
      const screen = button('▣', 'icon-button', () => openScreen(d.id)); screen.title = '查看截图'; screen.setAttribute('aria-label','查看截图'); actions.append(screen);
      const remove = button('×', 'icon-button danger remove-button', () => { state.deleting = d.id; $('#confirm-dialog').showModal(); }); remove.title = '删除实例'; remove.setAttribute('aria-label','删除实例'); actions.append(remove);
      host.append(card);
    }
    const active = d.run.active;
    card.classList.toggle('selected', state.selected.has(d.id));
    const check = $('.card-head>input', card); check.checked = state.selected.has(d.id); check.setAttribute('aria-label','选择 ' + d.name);
    $('.card-title h2', card).textContent = d.name; $('.card-title p', card).textContent = (emulatorSpec(d) ? `${emulatorSpec(d).kind === 'ldplayer' ? '雷电' : 'MuMu'} #${emulatorSpec(d).index} · ` : '') + (d.address.startsWith('emulator:') ? '启动后自动连接' : d.address);
    const power=d.power||{status:'unknown',on:false,supported:false};const pending=state.powerPending.get(d.id);
    const captureBusy=!!d.account_capture?.active;
    const powerBusy=state.powerPending.has(d.id)||['starting','launching_game','logging_in','stopping'].includes(power.status);
    const busy = !!active;
    const activity = $('.instance-activity',card);
    const reason = busy ? (d.run.phase || d.run.task || '正在执行任务配置') : '未执行配置';
    activity.dataset.busy = String(busy);
    $('.instance-activity-label',activity).textContent = busy ? '忙碌' : '空闲';
    activity.title = `${busy ? '忙碌' : '空闲'} · ${reason}`;
    activity.setAttribute('aria-label',`${d.name}：${busy ? '忙碌' : '空闲'}，${reason}`);
    const toggle=$('.power-control input',card);toggle.checked=state.powerPending.has(d.id)?pending:['starting','launching_game','logging_in'].includes(power.status)?true:power.status==='stopping'?false:power.on;toggle.disabled=powerBusy||captureBusy||!power.supported;toggle.setAttribute('aria-label',d.name+'开关机');
    $('.power-control span',card).textContent=powerBusy?(power.status==='logging_in'?'登录游戏中':power.status==='launching_game'?'启动游戏中':toggle.checked?'开机中':'关机中'):power.status==='unknown'?'未连接':power.on?'已开机':'已关机';
    $('.power-control',card).title=power.supported?'开机后自动登录并进入场景；关机会先停止任务':'此实例暂不支持开关机';
    $('.task-line span', card).textContent = d.run.task || (d.tasks.length ? '等待执行配置' : '请选择任务配置');
    $('.task-line small', card).textContent = d.run.total ? `${d.run.current} / ${d.run.total}` : '—';
    const pct = d.run.status === 'completed' ? 100 : (d.run.total ? ((d.run.current || 1) - 1) / d.run.total * 100 : 0);
    $('.progress i', card).style.width = pct + '%';
    const metas = $$('.card-meta span', card); metas[0].textContent = active?'配置队列':(labels[d.run.status]||'配置队列'); metas[1].textContent = d.tasks.length + ' 项任务';
    const run = $('.run-button', card);
    // A stable listener determines the latest state, including stop requests.
    if (run.dataset.active !== String(active) || run.dataset.bootOnly !== String(!!emulatorSpec(d) && !d.tasks.length)) {
      const updated = button(active ? '□ 停止配置' : '▷ 启动配置', active ? 'secondary run-button' : 'primary run-button', async () => { const latest = state.devices.find(x => x.id === d.id); await post(`devices/${d.id}/${latest.run.active ? 'stop' : 'start'}`); await refresh(); });
      updated.dataset.active = String(active); updated.dataset.bootOnly = String(!!emulatorSpec(d) && !d.tasks.length); run.replaceWith(updated);
    }
    $('.run-button', card).disabled = d.run.status === 'stopping' || (!active && !d.tasks.length) || powerBusy || captureBusy;
    $('.config-button', card).disabled = active || powerBusy || captureBusy; $('.remove-button', card).disabled = active || powerBusy || captureBusy;
    $('.config-button', card).textContent = d.profile_id ? '编辑配置' : '新建配置';
    $('.device-settings-button', card).disabled = active || powerBusy || captureBusy;
    const profileSelect = $('.card-profile select',card);
    const signature = JSON.stringify(state.profiles.map(p => [p.id,p.name,p.tasks.length]));
    if (profileSelect.dataset.signature !== signature) {
      const none = el('option','请选择任务配置'); none.value = '';
      profileSelect.replaceChildren(none,...state.profiles.map(p => {const option = el('option',`${p.name}（${p.tasks.length} 项）`);option.value=p.id;return option;}));
      profileSelect.dataset.signature=signature;
    }
    profileSelect.value = d.profile_id || ''; profileSelect.disabled = active || powerBusy || captureBusy || state.assigning.has(d.id);
    profileSelect.setAttribute('aria-label',d.name + '的任务配置');
    const detailAge=d.run.detail_updated_at?Math.floor((Date.now()-Date.parse(d.run.detail_updated_at))/1000):0;
    $('.task-detail',card).textContent=((powerBusy||(!active&&power.scene_status==='error'))&&power.phase?power.phase:d.run.task_detail||(active?'等待识别游戏任务栏…':''))+(active&&d.run.task_detail&&detailAge>15?`（${detailAge}秒前识别）`:'');
    const ratio=d.run.sub_total?Math.max(0,Math.min(100,d.run.sub_current/d.run.sub_total*100)):null;
    $('.sub-progress',card).hidden=ratio===null;$('.sub-progress i',card).style.width=(ratio||0)+'%';
    $('.task-phase',card).textContent=active&&d.run.phase?'当前步骤：'+d.run.phase:'';
  }
  $('#selection-count').textContent = `已选 ${state.selected.size} 个`;
  $('#batch-start').disabled = $('#batch-stop').disabled = state.selected.size === 0;
  $('#select-all').checked = list.length > 0 && list.every(d => state.selected.has(d.id));
  $('#select-all').indeterminate = list.some(d => state.selected.has(d.id)) && !$('#select-all').checked;
}
$('#search').addEventListener('input', render);
$$('.filter').forEach(b => b.addEventListener('click', () => { state.filter = b.dataset.filter; $$('.filter').forEach(x => x.classList.toggle('active', x === b)); render(); }));
$('#select-all').addEventListener('change', e => { for (const d of visibleDevices()) e.target.checked ? state.selected.add(d.id) : state.selected.delete(d.id); render(); });
async function batch(action) { const result = await post('batch', {ids:[...state.selected], action}); const errors = result.filter(x => !x.ok); toast(`${result.length - errors.length} 个实例${action === 'start' ? '已启动' : '已请求停止'}` + (errors.length ? '\n' + errors.map(x => (state.devices.find(d => d.id === x.id)?.name || x.id) + '：' + x.error).join('\n') : '')); await refresh(); }
$('#batch-start').addEventListener('click', () => guarded(() => batch('start'))); $('#batch-stop').addEventListener('click', () => guarded(() => batch('stop')));
$('#confirm-delete').addEventListener('click', () => guarded(async () => { await api('devices/' + state.deleting, {method:'DELETE'}); $('#confirm-dialog').close(); await refresh(); }));
function openAdd() {
  if (state.devices.length >= MAX_DEVICES) { toast('最多支持 ' + MAX_DEVICES + ' 个模拟器实例，请先删除不需要的实例'); return; }
  $('#scan-results').replaceChildren(); $('#add-dialog').showModal(); guarded(async () => { const platform = await api('emulators'); for (const p of platform.providers) { const o = $(`#emulator-kind option[value="${p.kind}"]`); o.disabled = !p.supported; } $('#emulator-platform').textContent = platform.platform === 'win32' ? '支持 MuMu 与雷电；找不到安装目录时可手动填写。' : '当前中控运行于 macOS，支持 MuMu；雷电需在 Windows 中控中接入。'; $('#mumu-app-path').placeholder = platform.platform === 'win32' ? '留空自动查找，或填写安装目录 / 命令行工具完整路径' : '/Applications/MuMuPlayer.app'; await scanMuMu(); }); }
async function scanMuMu() {
  const scan = $('#scan-mumu'); $('#emulator-kind').disabled = true; state.mumuRows = []; scan.disabled = true; scan.textContent = '读取中…';
  $('#import-all-mumu').disabled = true; $('#mumu-results').replaceChildren(el('p','正在读取模拟器实例…','muted'));
  try { state.mumuRows = await post('emulators/discover',{kind:$('#emulator-kind').value,app_path:$('#mumu-app-path').value.trim()}); renderMuMu(); }
  catch (err) { state.mumuRows = []; $('#mumu-results').replaceChildren(el('p',err.message,'muted')); }
  finally { $('#emulator-kind').disabled = false; scan.disabled = false; scan.textContent = '刷新列表'; }
}
function renderMuMu() {
  const host = $('#mumu-results'); host.replaceChildren();
  if (!state.mumuRows.length) host.append(el('p','未发现实例，请先在对应模拟器的多开器中创建。','muted'));
  for (const instance of state.mumuRows) {
    const row = el('div',undefined,'scan-row'); const title = el('div',instance.name);
    title.append(el('small',`#${emulatorSpec(instance).index} · ${instance.state === 'running' ? '已运行' : instance.state === 'stopped' ? '未启动' : instance.state} · ${instance.address || '启动后自动连接'}`));
    const added = state.devices.some(d => sameEmulator(d, instance));
    const add = button(added ? '已添加' : '添加','secondary',async () => {
      add.disabled = true;
      try { await post('emulators/import',{kind:$('#emulator-kind').value,app_path:emulatorSpec(instance).app_path,indexes:[emulatorSpec(instance).index]}); await refresh(); renderMuMu(); toast('已添加 ' + instance.name + '，可以直接启动游戏'); }
      catch (err) { add.disabled = false; throw err; }
    }); add.disabled = added || state.devices.length >= MAX_DEVICES; row.append(title,add); host.append(row);
  }
  $('#import-all-mumu').disabled = state.devices.length >= MAX_DEVICES || !state.mumuRows.some(i => !state.devices.some(d => sameEmulator(d, i)));
  if (state.devices.length >= MAX_DEVICES) host.append(el('p','已达到 '+MAX_DEVICES+' 个实例上限，删除不需要的实例后才能继续添加。','muted'));
}
$('#emulator-kind').addEventListener('change', () => { $('#mumu-app-path').value = ''; guarded(scanMuMu); });
$('#scan-mumu').addEventListener('click',() => guarded(scanMuMu));
$('#import-all-mumu').addEventListener('click',() => guarded(async () => {
  const remaining = state.mumuRows.filter(i => !state.devices.some(d => sameEmulator(d, i)));
  if (!remaining.length) return;
  const b = $('#import-all-mumu'); b.disabled = true;
  try { await post('emulators/import',{kind:$('#emulator-kind').value,app_path:emulatorSpec(remaining[0]).app_path,indexes:remaining.map(i => emulatorSpec(i).index)}); await refresh(); renderMuMu(); toast(`已添加 ${remaining.length} 个模拟器实例`); }
  finally { renderMuMu(); }
}));
$('#add-device').addEventListener('click', openAdd); $('#empty-add').addEventListener('click', openAdd);
$('#scan').addEventListener('click', () => guarded(async () => {
  const b = $('#scan'); b.disabled = true; b.textContent = '正在扫描…';
  try {
    const results = await post('discover', {adb_path:$('#adb-path').value.trim()}); const host = $('#scan-results'); host.replaceChildren();
    if (!results.length) host.append(el('p', '未发现设备。请填写模拟器自带的 ADB 路径，或手动添加。', 'muted'));
    for (const d of results) { const row = el('div', undefined, 'scan-row'); const title = el('div', d.name); title.append(el('small', d.address)); const added = state.devices.some(x => x.address === d.address); const b = button(added ? '已添加' : '添加', 'secondary', async () => { await post('devices', d); await refresh(); b.disabled = true; b.textContent = '已添加'; toast('已添加 ' + d.name); }); b.disabled = added; row.append(title,b); host.append(row); }
  } finally { b.disabled = false; b.textContent = '⌕ 扫描设备'; }
}));
$('#manual-form').addEventListener('submit', e => { e.preventDefault(); guarded(async () => { const adb = $('#adb-path').value.trim(); if (!adb) throw new Error('请填写 ADB 可执行文件路径'); await post('devices', {name:$('#device-name').value.trim(),address:$('#device-address').value.trim(),adb_path:adb}); $('#add-dialog').close(); e.target.reset(); await refresh(); toast('实例已添加，请配置任务队列'); }); });
function setView(view) {
  if(view==='monitor'&&!state.monitorAllowed){toast('监控中心仅支持本机或局域网访问');return;}
  state.view=view;
  for(const name of ['devices','profiles','activity','accounts','monitor']) {
    $('#'+name+'-view').hidden=view!==name;
    $('#nav-'+name).classList.toggle('nav-active',view===name);
    if(view===name) $('#nav-'+name).setAttribute('aria-current','page');
    else $('#nav-'+name).removeAttribute('aria-current');
  }
  $('#breadcrumb-view').textContent=({devices:'模拟器总览',profiles:'任务配置',activity:'活动日志',accounts:'账号中心',monitor:'监控中心'})[view];
  document.dispatchEvent(new CustomEvent('app:viewchange',{detail:view}));
  renderProfiles();
  if(view==='activity') guarded(loadActivity);
  if(view==='accounts') guarded(loadAccounts);
  if(view==='monitor') {renderMonitors(); if(!monitor.initialized){monitor.initialized=true;const d=state.devices.find(d=>d.power?.on);if(d)monitor.wanted.add(d.id);}syncMonitors();}
  else pauseMonitorStreams();
}
for(const name of ['devices','profiles','activity','accounts','monitor'])$('#nav-'+name).addEventListener('click',()=>setView(name));
function renderProfiles() {
  $('#profile-count').textContent=state.profiles.length;
  if(state.view!=='profiles') return;
  const search=$('#profile-search').value.trim().toLowerCase();
  const filtered=state.profiles.filter(p=>(p.name+' '+p.tasks.map(t=>t.name).join(' ')).toLowerCase().includes(search));
  $('#profiles-empty').hidden=state.profiles.length>0; $('#profiles-no-results').hidden=!state.profiles.length||filtered.length>0;
  const signature=JSON.stringify([search,state.profiles]); if(signature===state.profilesSignature) return; state.profilesSignature=signature;
  const host=$('#profiles-list'); host.replaceChildren();
  for(const p of filtered) {
    const card=el('article',undefined,'profile-card'); const title=el('div',undefined,'profile-card-title');
    title.append(el('h2',p.name));card.append(title);
    const tasks=el('div',undefined,'profile-task-summary');
    p.tasks.forEach((t,i)=>tasks.append(el('span',`${i+1}. ${t.name}`)));card.append(tasks);
    card.append(el('p',p.devices.length?`使用实例：${p.devices.map(d=>d.name).join('、')}`:'尚未绑定实例 · 可发送到一个或多个实例','profile-usage'));
    const actions=el('div',undefined,'profile-card-actions');actions.append(el('span',`${p.tasks.length} 项任务`,'muted'),button('发送到实例','primary profile-send-button',()=>openProfileSend(p.id)),button('编辑','secondary',()=>openProfileEditor(p)),button('复制','secondary',async()=>{await post('profiles/'+p.id+'/duplicate');await refresh();toast('配置已复制，可以单独编辑');}));
    const remove=button('删除','subtle danger',()=>{state.deletingProfile=p.id;$('#delete-profile-name').textContent=p.name;$('#delete-profile-dialog').showModal();});remove.disabled=p.devices.length>0;remove.title=p.devices.length?'先在引用实例上切换配置才能删除':'删除配置';actions.append(remove);card.append(actions);host.append(card);
  }
}
$('#profile-search').addEventListener('input',renderProfiles);
$('#new-profile').addEventListener('click',()=>openProfileEditor());$('#empty-new-profile').addEventListener('click',()=>openProfileEditor());
$('#confirm-delete-profile').addEventListener('click',()=>guarded(async()=>{await api('profiles/'+state.deletingProfile,{method:'DELETE'});$('#delete-profile-dialog').close();await refresh();toast('任务配置已删除');}));
async function setDevicePower(id,on) {
  state.powerPending.set(id,on);render();
  try {await api('devices/'+id+'/power',{method:'PUT',body:JSON.stringify({on})});await refresh();toast(on?'模拟器已开机，已进入游戏场景':'模拟器已关机');}
  finally {state.powerPending.delete(id);await refresh();}
}
async function assignDeviceProfile(id,profileId) {
  state.assigning.add(id);render();
  try {await api('devices/'+id+'/profile',{method:'PUT',body:JSON.stringify({profile_id:profileId})});await refresh();toast(profileId?'已选用任务配置，下次启动生效':'已取消任务配置，请选择其他配置后再启动');}
  finally {state.assigning.delete(id);await refresh();}
}
function openConfig(id) {
  const d=state.devices.find(x=>x.id===id);const profile=state.profiles.find(p=>p.id===d.profile_id);
  openProfileEditor(profile || {name:d.name+'配置',tasks:d.tasks}, profile?null:id);
}
function openProfileEditor(profile=null,bindDeviceId=null) {
  state.editingProfile=profile?.id?{id:profile.id,version:profile.version}:null;state.bindDeviceId=bindDeviceId;
  state.queue=structuredClone(profile?.tasks||[]);state.pickedTasks.clear();state.openTaskCategories=new Set(['个人日常']);state.collapsedSearchCategories.clear();
  $('#config-title').textContent=profile?.id?'编辑任务配置':'新建任务配置';$('#profile-name').value=profile?.name||'';
  const bound=profile?.devices||[];$('#profile-sharing-note').textContent=bound.length?`此配置由 ${bound.map(d=>d.name).join('、')} 共用。保存后下次启动生效，正在运行的队列不受影响。`:bindDeviceId?'保存后自动选用于当前实例，也可供其他实例选用。':'勾选多个任务加入队列，调整顺序与选项后命名保存。';
  $('#task-search').value='';renderLibrary();renderQueue();$('#config-dialog').showModal();$('#profile-name').focus();$('#profile-name').select();
}
function updatePickedCount() {$('#add-picked-tasks').textContent=`加入队列（${state.pickedTasks.size}）`;$('#add-picked-tasks').disabled=state.pickedTasks.size===0;}
function renderLibrary() {
  const search=$('#task-search').value.trim().toLowerCase();const host=$('#task-library');const scroll=host.scrollTop;host.replaceChildren();$('#task-count').textContent=state.catalog.tasks.length+' 项';
  const categories=state.catalog.categories||['个人日常','组队日常','周常','日常功能','养成服务'];
  let matched=0;
  for(const category of categories) {
    const tasks=state.catalog.tasks.filter(t=>(t.category||'日常功能')===category&&t.name.toLowerCase().includes(search)).sort((a,b)=>(a.category_order||0)-(b.category_order||0));
    if(!tasks.length)continue;matched+=tasks.length;
    const group=el('section',undefined,'task-category');const header=el('div',undefined,'task-category-header');
    const open=search?!state.collapsedSearchCategories.has(category):state.openTaskCategories.has(category);
    const toggle=button((open?'▾ ':'▸ ')+category,'category-toggle',()=>{
      if(search)open?state.collapsedSearchCategories.add(category):state.collapsedSearchCategories.delete(category);
      else open?state.openTaskCategories.delete(category):state.openTaskCategories.add(category);
      renderLibrary();
    });toggle.setAttribute('aria-expanded',String(open));
    const all=el('input');all.type='checkbox';all.setAttribute('aria-label','选择'+category+'全部任务');all.title='选择此分类中当前显示的任务';
    const sync=()=>{all.checked=tasks.every(t=>state.pickedTasks.has(t.name));all.indeterminate=!all.checked&&tasks.some(t=>state.pickedTasks.has(t.name));};sync();
    all.addEventListener('change',()=>{for(const task of tasks)all.checked?state.pickedTasks.add(task.name):state.pickedTasks.delete(task.name);renderLibrary();});
    header.append(toggle,el('small',tasks.length+' 项'),all);group.append(header);
    if(open){const children=el('div',undefined,'task-category-children');
      for(const task of tasks){const row=el('div',undefined,'library-row');const label=el('label');const check=el('input');check.type='checkbox';check.checked=state.pickedTasks.has(task.name);
        check.addEventListener('change',()=>{check.checked?state.pickedTasks.add(task.name):state.pickedTasks.delete(task.name);updatePickedCount();sync();});label.append(check,el('span',task.name));
        row.append(label,button('＋','',()=>{state.queue.push({name:task.name,options:{}});renderQueue();}));children.append(row);
      }group.append(children);
    }host.append(group);
  }
  if(!matched)host.append(el('p','没有匹配任务，试试其他关键词。','muted'));
  host.scrollTop=scroll;updatePickedCount();
}
$('#task-search').addEventListener('input',()=>{state.collapsedSearchCategories.clear();renderLibrary();});
$('#add-picked-tasks').addEventListener('click',()=>{for(const name of state.pickedTasks)state.queue.push({name,options:{}});state.pickedTasks.clear();renderLibrary();renderQueue();});
function openDeviceSettings(id) {
  const d=state.devices.find(x=>x.id===id);state.settingsId=id;$('#settings-device-name').value=d.name;
  $('#device-settings-dialog').showModal();
}
$('#save-device-settings').addEventListener('click',()=>guarded(async()=>{await api('devices/'+state.settingsId+'/settings',{method:'PATCH',body:JSON.stringify({name:$('#settings-device-name').value.trim()})});$('#device-settings-dialog').close();await refresh();toast('实例设置已保存');}));
function chosenValue(spec, value) { return value ?? spec.default_case ?? spec.default ?? (spec.type === 'checkbox' ? [] : spec.cases?.[0]?.name); }
function renderOption(name, values, ancestors = []) {
  const host = el('div', undefined, 'option-group'); if (ancestors.includes(name)) return host;
  const spec = state.catalog.options[name]; if (!spec) return host;
  const label = el('label', name); host.append(label);
  if (spec.description) host.append(el('p', spec.description));
  if (spec.type === 'input') {
    const current = values[name] || {}; values[name] = current;
    for (const field of spec.inputs) { const l = el('label', field.name); const input = el('input'); input.value = current[field.name] ?? field.default ?? ''; input.type = /apikey|密钥/i.test(field.name) ? 'password' : 'text'; if (field.pipeline_type === 'int') input.inputMode = 'numeric'; if (field.description) input.placeholder = field.description; input.addEventListener('input', () => current[field.name] = input.value); l.append(input); host.append(l); }
  } else {
    const selected = chosenValue(spec, values[name]); const children = el('div');
    function renderChildren() { children.replaceChildren(); const choice = chosenValue(spec, values[name]); for (const c of spec.cases || []) if ((Array.isArray(choice) ? choice : [choice]).includes(c.name)) { if (c.description) children.append(el('p', c.description)); for (const child of c.option || []) children.append(renderOption(child, values, [...ancestors,name])); } }
    if (spec.type === 'checkbox') {
      for (const c of spec.cases) { const l = el('label', undefined, 'check-option'); const input = el('input'); input.type = 'checkbox'; input.checked = selected.includes(c.name); input.addEventListener('change', () => { values[name] = [...host.querySelectorAll(':scope > label.check-option input:checked')].map(i => i.value); renderChildren(); }); input.value = c.name; l.append(input,el('span',c.name)); host.append(l); }
    } else {
      const select = el('select'); for (const c of spec.cases) { const o = el('option', c.name === 'Yes' ? '开启' : c.name === 'No' ? '关闭' : c.name); o.value = c.name; select.append(o); } select.value = selected; select.setAttribute('aria-label',name); select.addEventListener('change', () => { values[name] = select.value; renderChildren(); }); label.append(select);
    }
    host.append(children); renderChildren();
  }
  return host;
}
function renderQueue() {
  const host = $('#task-queue'); host.replaceChildren();
  if (!state.queue.length) { host.append(el('p','从左侧勾选任务并加入队列，组成一份可复用的任务配置。','muted')); return; }
  state.queue.forEach((item, i) => {
    const task = state.catalog.tasks.find(t => t.name === item.name); const row = el('div', undefined, 'queue-item'); const heading = el('div', undefined, 'queue-heading'); heading.append(el('span', `${String(i + 1).padStart(2,'0')}  ${item.name}`));
    heading.append(button('说明','subtle',async () => { const info = await api('description?name=' + encodeURIComponent(item.name)); $('#description-title').textContent = item.name; $('#description-text').textContent = info.text; $('#description-dialog').showModal(); }));
    const up = button('↑','secondary',() => { [state.queue[i-1],state.queue[i]] = [state.queue[i],state.queue[i-1]]; renderQueue(); }); up.disabled = i === 0; up.setAttribute('aria-label','上移 ' + item.name);
    const down = button('↓','secondary',() => { [state.queue[i+1],state.queue[i]] = [state.queue[i],state.queue[i+1]]; renderQueue(); }); down.disabled = i === state.queue.length - 1; down.setAttribute('aria-label','下移 ' + item.name);
    heading.append(up,down,button('×','subtle danger',() => { state.queue.splice(i,1); renderQueue(); })); row.append(heading);
    item.options ||= {}; for (const name of task?.option || []) row.append(renderOption(name, item.options)); host.append(row);
  });
}
$('#save-profile').addEventListener('click',()=>guarded(async()=>{
  const b=$('#save-profile');b.disabled=true;
  try {
    const editing=state.editingProfile;const body={name:$('#profile-name').value.trim(),tasks:state.queue};if(editing)body.version=editing.version;
    const saved=await api('profiles'+(editing?'/'+editing.id:''),{method:editing?'PUT':'POST',body:JSON.stringify(body)});
    state.editingProfile={id:saved.id,version:saved.version};$('#config-dialog').close();
    if(state.bindDeviceId) {
      try {await api('devices/'+state.bindDeviceId+'/profile',{method:'PUT',body:JSON.stringify({profile_id:saved.id})});toast('配置已保存，并已选用于当前实例');}
      catch(err) {toast('配置已保存；实例选用失败：'+err.message);}
    } else toast('任务配置已保存，可在实例卡片中直接选择');
    await refresh();
  } finally {b.disabled=false;}
}));
async function openLogs(id) { state.logId = id; $('#logs-title').textContent = state.devices.find(d => d.id === id).name + ' · 运行日志'; $('#logs').textContent = '正在读取…'; $('#logs-dialog').showModal(); await refreshLogs(); }
async function refreshLogs() { if (!$('#logs-dialog').open || !state.logId) return; const id = state.logId; const data = await api(`devices/${id}/logs`); if (id !== state.logId) return; const log = $('#logs'); const bottom = log.scrollHeight - log.scrollTop - log.clientHeight < 70; log.textContent = data.logs.length ? data.logs.map(x => `${new Date(x.time).toLocaleTimeString()}  ${x.message}`).join('\n') : '暂无日志。配置并启动任务后，这里将显示执行信息。'; $('#log-status').textContent = `${labels[data.run.status] || data.run.status} ${data.run.task ? '· ' + data.run.task : ''}`; if (bottom) log.scrollTop = log.scrollHeight; }
async function openScreen(id) { state.screenId = id; $('#screen-title').textContent = state.devices.find(d => d.id === id).name + ' · 当前画面'; $('#screen-image').removeAttribute('src'); $('#screen-dialog').showModal(); await screenshot(); }
async function screenshot() { const b = $('#refresh-screen'); b.disabled = true; $('#screen-state').textContent = '正在获取设备截图…'; try { const blob = await api(`devices/${state.screenId}/screenshot`, {binary:true}); if (state.screenURL) URL.revokeObjectURL(state.screenURL); state.screenURL = URL.createObjectURL(blob); $('#screen-image').src = state.screenURL; $('#screen-state').textContent = '更新于 ' + new Date().toLocaleTimeString(); } catch (err) { $('#screen-state').textContent = err.message; } finally { b.disabled = false; } }
$('#refresh-screen').addEventListener('click', () => guarded(screenshot));
setInterval(async () => {
  if (state.pollBusy && Date.now() - (state.pollBusyAt || 0) > 20000) { state.pollBusy = false; }
  if ((state.authRequired && !state.token) || $('#shell').hidden || state.pollBusy || document.hidden) return;
  state.pollBusy = true; state.pollBusyAt = Date.now(); try { await refresh(); await refreshLogs(); } catch (err) { $('#connection').textContent = '连接中断，正在重试'; } finally { state.pollBusy = false; } }, 2000);
async function bootstrap() {
  const response=await fetch('/health');if(!response.ok)throw new Error('中控服务暂不可用');
  const info=await response.json();state.authRequired=!!info.auth_required;
  state.monitorAllowed=info.monitor!==false;
  $('#logout').hidden=!state.authRequired;
  if(!state.authRequired){state.token='';sessionStorage.removeItem('mhxy-token');await connect();}
  else if(state.token)await connect();else $('#login').hidden=false;
}
guarded(bootstrap);

const activityState={runs:[],device:'',status:'all'};
const activityLabels={starting:'启动中',running:'进行中',completed:'已完成',failed:'失败',stopped:'已停止',ready:'已就绪'};
const activityTaskLabels={completed:'完成',failed:'失败',running:'进行中',pending:'等待',skipped:'未执行',stopped:'已停止'};
function secondsBetween(from,to){const a=Date.parse(from),b=Date.parse(to);return Number.isFinite(a)&&Number.isFinite(b)?Math.max(0,(b-a)/1000):null;}
function fmtDuration(value){if(value==null||!Number.isFinite(value))return '—';const s=Math.max(0,Math.round(value));if(s<60)return s+' 秒';const m=Math.floor(s/60),sec=s%60;if(m<60)return sec?m+' 分 '+sec+' 秒':m+' 分';const h=Math.floor(m/60),mm=m%60;return mm?h+' 小时 '+mm+' 分':h+' 小时';}
const STUCK_SECONDS=600;
function taskMedians(){
  const samples=new Map();
  for(const run of activityState.runs)for(const task of run.tasks||[]){
    if(task.status==='completed'&&typeof task.seconds==='number'){
      if(!samples.has(task.name))samples.set(task.name,[]);
      samples.get(task.name).push(task.seconds);
    }
  }
  const medians=new Map();
  for(const [name,list] of samples){list.sort((a,b)=>a-b);const mid=Math.floor(list.length/2);medians.set(name,list.length%2?list[mid]:(list[mid-1]+list[mid])/2);}
  return medians;
}
function taskFlag(task,stamp,medians){
  if(task.name==='编组自动组队')return '';

  if(task.status==='running'&&task.started_at){
    const seconds=secondsBetween(task.started_at,stamp);
    if(seconds!=null&&seconds>=STUCK_SECONDS)return 'stuck';
  }
  if(task.status==='completed'&&typeof task.seconds==='number'){
    const median=medians.get(task.name);
    if(median!=null&&median>=180&&task.seconds<=median*.5)return 'empty';
  }
  return '';
}
function fmtClock(iso){const d=new Date(iso||0);if(Number.isNaN(d.getTime()))return '—';const now=new Date(),pad=n=>String(n).padStart(2,'0');const hm=pad(d.getHours())+':'+pad(d.getMinutes());return d.toDateString()===now.toDateString()?hm:(d.getMonth()+1)+'月'+d.getDate()+'日 '+hm;}
async function loadActivity(){try{const data=await api('activity?limit=80');activityState.runs=data.runs||[];}catch(err){activityState.runs=activityState.runs||[];}renderActivity();}
function renderActivity(){
  if(state.view!=='activity')return;
  const select=$('#activity-device'),signature=state.devices.map(d=>d.id+'\u0000'+d.name).join('|');
  if(select.dataset.signature!==signature){
    const previous=activityState.device;
    select.replaceChildren(new Option('全部实例',''));
    for(const d of state.devices)select.append(new Option(d.name,d.id));
    select.dataset.signature=signature;select.value=previous;
  }
  for(const b of $$('#activity-filters button'))b.classList.toggle('active',b.dataset.status===activityState.status);
  const now=Date.now(),stamp=new Date(now).toISOString();
  const rows=activityState.runs.filter(run=>(!activityState.device||run.device_id===activityState.device)&&(activityState.status==='all'||(activityState.status==='running'?run.status==='starting'||run.status==='running':run.status===activityState.status)));
  const host=$('#activity-list');host.replaceChildren();
  $('#activity-empty').hidden=rows.length>0;
  $('#activity-summary').textContent=rows.length?'最近 '+rows.length+' 次记录':'';
  const medians=taskMedians();
  for(const run of rows){
    const tasks=run.tasks||[];
    const flags=tasks.map(task=>taskFlag(task,stamp,medians));
    const emptyCount=flags.filter(flag=>flag==='empty').length,stuckCount=flags.filter(flag=>flag==='stuck').length;
    const card=el('article',undefined,'activity-card'),head=el('div',undefined,'activity-head'),title=el('div',undefined,'activity-title');
    const span=run.finished_at?fmtClock(run.started_at)+' – '+fmtClock(run.finished_at):fmtClock(run.started_at)+' 开始';
    title.append(el('span',activityLabels[run.status]||run.status,'badge '+(run.status||'')),el('h2',(run.device_name||'实例')+' · '+(run.profile_name||'未命名配置')),
      el('time',span+' · '+(tasks.length?tasks.length+' 项任务':'仅打开游戏')));
    const total=secondsBetween(run.started_at,run.finished_at||stamp);
    const done=tasks.filter(t=>t.status==='completed').length,failed=tasks.filter(t=>t.status==='failed').length;
    const summary=el('div',undefined,'activity-summary');
    summary.append(el('div',((run.status==='running'||run.status==='starting')?'已运行 ':'总用时 ')+fmtDuration(total)),el('div','完成 '+done+(failed?' · 失败 '+failed:'')));
    if(emptyCount)summary.append(el('div','疑似空跑 '+emptyCount+' 项','activity-warn'));
    if(stuckCount)summary.append(el('div','疑似卡住 '+stuckCount+' 项','activity-alert'));
    head.append(title,summary);card.append(head);
    if(run.error)card.append(el('p','失败原因：'+run.error,'activity-error'));
    const list=el('ol',undefined,'activity-tasks');
    const max=Math.max(1,...tasks.map(t=>t.seconds||0));
    tasks.forEach((task,index)=>{
      const live=task.status==='running';
      const cls=task.status==='completed'?'done':task.status==='failed'?'failed':live?'live':'';
      const row=el('li',undefined,'activity-task '+cls);
      const seconds=live&&task.started_at?secondsBetween(task.started_at,stamp):task.seconds;
      const bar=el('span',undefined,'bar'),fill=el('i');
      fill.style.width=(seconds==null?0:Math.max(3,Math.round(Math.min(1,seconds/max)*100)))+'%';
      bar.append(fill);
      const nameCell=el('span',task.name,'name');
      if(flags[index]==='empty')nameCell.append(el('i','疑似空跑','flag'));
      if(flags[index]==='stuck')nameCell.append(el('i','疑似卡住','flag stuck'));
      row.append(el('span',String(index+1),'index'),nameCell,bar,el('span',fmtDuration(seconds),'time'),el('span',task.status==='running'&&task.team_role==='member'?'跟队中':activityTaskLabels[task.status]||task.status,'state'));
      list.append(row);
    });
    if(!tasks.length)list.append(el('p','本次只打开游戏，没有执行日常任务。','muted'));
    card.append(list);host.append(card);
  }
}
$('#activity-device').addEventListener('change',event=>{activityState.device=event.target.value;renderActivity();});
for(const b of $$('#activity-filters button'))b.addEventListener('click',()=>{activityState.status=b.dataset.status;renderActivity();});
const updates={checking:false,info:null};
function renderEngine(){
  const v=state.version;if(!v)return;
  const kernel=$('#kernel-version'),project=$('#project-version');
  kernel.textContent='内核 MaaFw '+(v.kernel.installed||'未知');
  kernel.title=v.kernel.matches?'与 requirements.txt 要求一致':'项目要求 '+(v.kernel.required||'未知');
  project.textContent='项目 '+(v.local.version||'未知')+(v.local.dirty?' · 本地修改':'');
  project.title='提交 '+(v.local.commit||'?')+' · '+(v.local.date||'');
}
async function loadVersion(){state.version=await api('version');renderEngine();}
function formatNotes(text){return text.split('\n').map(line=>line.replace(/^#{1,6}\s*/,'').replace(/\*\*/g,'').trimEnd()).filter((line,index,rows)=>!(line===''&&rows[index-1]==='')).join('\n').trim();}
async function checkUpdate(auto){
  if(updates.checking)return;updates.checking=true;
  const dialog=$('#update-dialog'),body=$('#update-body'),applyButton=$('#apply-update');
  applyButton.hidden=true;
  if(!auto){if(!dialog.open)dialog.showModal();body.replaceChildren(el('p','正在检查更新…','muted'));}
  try{
    if(!state.version)await loadVersion();
    const info=await api('version/check');updates.info=info;
    if(auto){
      if(info.has_update&&!info.error){
        const result=await api('version/update',{method:'POST'});
        if(result.changed){toast('已自动更新到 '+result.after+'，重启服务后生效');await loadVersion();}
      }
      return;
    }
    body.replaceChildren();
    const v=state.version;
    body.append(el('p','当前：项目 '+(v.local.version||'未知')+'（'+(v.local.commit||'?')+'）· 内核 MaaFw '+(v.kernel.installed||'未知'),'update-current'));
    if(info.error){body.append(el('p',info.error,'activity-alert'));return;}
    body.append(el('p','最新：'+(info.latest||'未知'),'update-latest'));
    if(!info.has_update){body.append(el('p','已经是最新版本。','muted'));return;}
    if(info.notes)body.append(el('pre',formatNotes(info.notes),'update-notes'));
    applyButton.hidden=false;
    if($('#auto-update').checked)await applyUpdate();
  }catch(err){
    if(!auto)body.append(el('p',err.message,'activity-alert'));
  }finally{updates.checking=false;}
}
async function applyUpdate(){
  const body=$('#update-body'),button=$('#apply-update'),label=button.textContent;
  button.disabled=true;button.textContent='更新中…';
  try{
    const result=await api('version/update',{method:'POST'});
    updates.info=null;button.hidden=true;
    body.append(el('p','已更新：'+(result.before||'?')+' → '+(result.after||'?')+(result.restart?'，重启服务后生效':''),'update-done'));
    await loadVersion();
  }catch(err){body.append(el('p',err.message,'activity-alert'));}
  finally{button.disabled=false;button.textContent=label;}
}
$('#check-update').addEventListener('click',()=>guarded(()=>checkUpdate(false)));
$('#apply-update').addEventListener('click',()=>guarded(applyUpdate));
const autoUpdateBox=$('#auto-update');
autoUpdateBox.checked=localStorage.getItem('mhxy-auto-update')==='1';
autoUpdateBox.addEventListener('change',()=>localStorage.setItem('mhxy-auto-update',autoUpdateBox.checked?'1':'0'));
const monitor={wanted:new Set(),active:new Map(),initialized:false,large:null};
function monitorCard(id){return [...$('#monitor-grid').children].find(c=>c.dataset.id===id);}
function renderMonitors(){
  const host=$('#monitor-grid'),ids=new Set(state.devices.map(d=>d.id));
  for(const card of [...host.children])if(!ids.has(card.dataset.id)){monitor.wanted.delete(card.dataset.id);stopMonitor(card.dataset.id);card.remove();}
  for(const d of state.devices){
    let card=monitorCard(d.id);
    if(!card){
      card=el('article',undefined,'monitor-card');card.dataset.id=d.id;
      const heading=el('div',undefined,'monitor-heading');heading.append(el('h2',d.name),el('span','已暂停','monitor-status'));
      const preview=button('','monitor-preview',()=>{const img=$('img',card);if(!img.getAttribute('src')){toast('画面还没开始，先点“开始观看”');return;}monitor.large=d.id;$('#monitor-title').textContent=d.name+' · 实时画面';$('#monitor-large').src=img.src;$('#monitor-dialog').showModal();});
      const image=el('img');image.alt=d.name+'实时画面';preview.append(image,el('span','点击观看开始串流','monitor-placeholder'));
      card.append(heading,preview,el('div',undefined,'monitor-bottom'));host.append(card);
      $('.monitor-bottom',card).append(el('small','尚未连接','monitor-time'),button('开始观看','secondary monitor-toggle',()=>{if(monitor.wanted.has(d.id)){monitor.wanted.delete(d.id);stopMonitor(d.id);}else monitor.wanted.add(d.id);syncMonitors();}));
    }
    $('h2',card).textContent=d.name;
    $('.monitor-toggle',card).textContent=monitor.wanted.has(d.id)?'暂停观看':'开始观看';
  }
}
function stopMonitor(id){const active=monitor.active.get(id);if(active){clearTimeout(active.timer);active.controller.abort();if(active.url)URL.revokeObjectURL(active.url);monitor.active.delete(id);}const card=monitorCard(id);if(card){$('.monitor-status',card).textContent='已暂停';$('.monitor-status',card).classList.remove('is-live');const image=$('img',card);image.onerror=null;image.removeAttribute('src');$('.monitor-placeholder',card).hidden=false;}if(monitor.large===id)$('#monitor-large').removeAttribute('src');}
function pauseMonitorStreams(){for(const id of [...monitor.active.keys()])stopMonitor(id);}
function syncMonitors(){
  if(state.view!=='monitor'||document.hidden||$('#shell').hidden){pauseMonitorStreams();return;}
  for(const id of monitor.wanted)if(!monitor.active.has(id)&&monitorCard(id))startMonitor(id);
  renderMonitors();
}
async function startMonitor(id){
  const active={controller:new AbortController(),url:null,mode:'fetch',frames:0,timer:0};monitor.active.set(id,active);
  const card=monitorCard(id),status=$('.monitor-status',card),image=$('img',card);
  status.textContent='连接中…';
  const fallback=()=>{
    if(active.mode!=='fetch'||state.token)return false;
    active.mode='img';clearTimeout(active.timer);active.controller.abort();
    image.onerror=()=>{if(monitor.active.get(id)!==active)return;status.textContent='画面连接失败，重连中';status.classList.remove('is-live');setTimeout(()=>{if(monitor.active.get(id)===active){stopMonitor(id);syncMonitors();}},1800);};
    image.src='/api/devices/'+id+'/stream';
    $('.monitor-placeholder',card).hidden=true;
    status.textContent='实时画面';status.classList.add('is-live');
    $('.monitor-time',card).textContent='更新于 '+new Date().toLocaleTimeString();
    return true;
  };
  active.timer=setTimeout(()=>{if(!active.frames)fallback();},5000);
  try{
    const response=await fetch('/api/devices/'+id+'/stream',{headers:state.token?{Authorization:'Bearer '+state.token}:{},signal:active.controller.signal,cache:'no-store'});
    if(!response.ok)throw Error('画面连接失败');
    if(!response.body){if(!fallback())throw Error('浏览器不支持画面串流');return;}
    const reader=response.body.getReader();let buffer=new Uint8Array();const decoder=new TextDecoder();
    while(true){
      const {value,done}=await reader.read();if(done)break;
      const joined=new Uint8Array(buffer.length+value.length);joined.set(buffer);joined.set(value,buffer.length);buffer=joined;
      if(buffer.length>6000000)throw Error('画面数据异常');
      while(true){
        let end=-1;for(let i=0;i<buffer.length-3;i++)if(buffer[i]===13&&buffer[i+1]===10&&buffer[i+2]===13&&buffer[i+3]===10){end=i;break;}
        if(end<0)break;const header=decoder.decode(buffer.subarray(0,end)),length=Number(/Content-Length:\s*(\d+)/i.exec(header)?.[1]);
        if(!length||length>5000000)throw Error('画面数据无效');if(buffer.length<end+4+length)break;
        const jpeg=buffer.slice(end+4,end+4+length);buffer=buffer.slice(end+4+length);
        active.frames++;clearTimeout(active.timer);
        const url=URL.createObjectURL(new Blob([jpeg],{type:'image/jpeg'})),old=active.url;active.url=url;
        image.src=url;$('.monitor-placeholder',card).hidden=true;
        if(monitor.large===id)$('#monitor-large').src=url;
        if(old)URL.revokeObjectURL(old);
        const live=/X-Frame-Status:\s*live/i.test(header);status.textContent=live?'实时画面':'设备离线 · 等待开机';status.classList.toggle('is-live',live);
        $('.monitor-time',card).textContent='更新于 '+new Date().toLocaleTimeString();
      }
    }
    if(!active.controller.signal.aborted)throw Error('串流已断开');
  }catch(error){
    if(active.controller.signal.aborted)return;
    clearTimeout(active.timer);
    if(active.frames===0&&fallback())return;
    status.textContent=error.message+'，重连中';
    setTimeout(()=>{if(monitor.active.get(id)===active){stopMonitor(id);syncMonitors();}},1800);
  }
}
$('#monitor-all').addEventListener('click',()=>{for(const d of state.devices)if(d.power?.on)monitor.wanted.add(d.id);syncMonitors();});
$('#monitor-pause').addEventListener('click',()=>{monitor.wanted.clear();pauseMonitorStreams();renderMonitors();});
$('#monitor-dialog').addEventListener('close',()=>{monitor.large=null;$('#monitor-large').removeAttribute('src');});
document.addEventListener('visibilitychange',syncMonitors);
window.addEventListener('pagehide',pauseMonitorStreams);

// 监控中心画面排列：单列 / 双列 / 九宫格
const monitorLayouts={1:'单列',2:'双列',3:'九宫格'};
function applyMonitorLayout(layout){
  layout=monitorLayouts[layout]?String(layout):'2';
  const grid=$('#monitor-grid');
  if(grid)grid.dataset.layout=layout;
  for(const b of $$('#monitor-layout button')){
    const on=b.dataset.layout===layout;
    b.classList.toggle('active',on);
    b.setAttribute('aria-pressed',String(on));
  }
  try{localStorage.setItem('mhxy-monitor-layout',layout);}catch{}
}
for(const b of $$('#monitor-layout button'))b.addEventListener('click',()=>applyMonitorLayout(b.dataset.layout));
applyMonitorLayout(localStorage.getItem('mhxy-monitor-layout')||'2');
