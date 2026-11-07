'use strict';
/* Presentation and navigation only: no emulator or task is started by this file. */
(() => {
  let taskIcons={};
  const viewLabels={devices:'模拟器总览',profiles:'任务配置',activity:'活动日志',accounts:'账号中心',monitor:'监控中心'};
  const symbolPaths={devices:'<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4"/>',profiles:'<rect x="4" y="3" width="16" height="18" rx="3"/><path d="M8 8h8m-8 4h8m-8 4h4"/>',activity:'<path d="M4 5h16M4 12h16M4 19h16"/>',accounts:'<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',monitor:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',plus:'<path d="M12 4v16M4 12h16"/>',book:'<path d="M12 5C9 3 5 3 2 4v15c3-1 7-1 10 1 3-2 7-2 10-1V4c-3-1-7-1-10 1Zm0 0v15"/>',team:'<circle cx="9" cy="8" r="3"/><path d="M2 21v-2a7 7 0 0 1 14 0v2M17 5a3 3 0 0 1 0 6m2 3a6 6 0 0 1 3 5v2"/>',calendar:'<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4m10-4v4M3 11h18m-13 4h2m4 0h2"/>',spark:'<path d="m12 2 2.5 6.5L21 11l-6.5 2.5L12 20l-2.5-6.5L3 11l6.5-2.5L12 2Zm7 15 1 2 2 1-2 1-1 2-1-2-2-1 2-1Z"/>',bag:'<rect x="4" y="7" width="16" height="14" rx="3"/><path d="M8 7V5a4 4 0 0 1 8 0v2m-8 6h8m-4-2v4"/>'};
  function icon(name){const span=el('span');span.innerHTML=`<svg viewBox="0 0 24 24" aria-hidden="true">${symbolPaths[name]||symbolPaths.book}</svg>`;return span;}
  const mac=/Mac|iPhone|iPad/.test(navigator.platform);
  const modifier=mac?'⌘':'Ctrl+';
  const tools=el('div',undefined,'header-tools');
  const quick=button('', 'command-trigger',openCommands);
  quick.setAttribute('aria-label','快速导航');quick.title=`快速导航（${modifier}K）`;
  quick.append(icon('search').firstChild,el('span','快速导航'),el('kbd',`${modifier}K`));
  tools.append(quick,$('#check-update'),$('.connection'));
  $('header').append(tools);
  const footerMeta=el('span',undefined,'footer-meta');
  footerMeta.append($('#kernel-version'),$('#project-version'));
  $('footer').append(footerMeta);
  $('#nav-devices').setAttribute('aria-current','page');
  for(const field of $$('#search,#profile-search,#task-search'))field.type='search';
  for(const dialog of $$('dialog')){
    const heading=$('h2',dialog);
    if(heading){if(!heading.id)heading.id=dialog.id+'-heading';dialog.setAttribute('aria-labelledby',heading.id);}
  }
  // Read-only dialogs dismiss on their backdrop; editing dialogs retain explicit controls.
  for(const dialog of $$('#logs-dialog,#screen-dialog,#monitor-dialog,#description-dialog')){
    dialog.addEventListener('pointerdown',event=>{
      if(event.target!==dialog)return;
      const r=dialog.getBoundingClientRect();
      if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();
    });
  }
  document.addEventListener('app:viewchange',event=>{
    const section=$('#'+event.detail+'-view');
    for(const view of Object.keys(viewLabels))$('#'+view+'-view').classList.remove('apple-view-enter');
    if(!matchMedia('(prefers-reduced-motion: reduce)').matches){section.classList.add('apple-view-enter');setTimeout(()=>section.classList.remove('apple-view-enter'),300);}
    if(event.detail==='profiles')renderWorkspaceLibrary();
    window.scrollTo({top:0,behavior:'instant'});
  });

  const commandDialog=el('dialog',undefined,'apple-command-dialog');commandDialog.id='command-dialog';commandDialog.setAttribute('aria-label','快速导航');
  const commandSearch=el('div',undefined,'command-search');commandSearch.append(icon('search').firstChild);
  const commandInput=el('input');commandInput.id='command-input';commandInput.placeholder='搜索页面、实例或操作…';commandInput.type='search';commandInput.autocomplete='off';commandInput.setAttribute('role','combobox');commandInput.setAttribute('aria-label','搜索快速导航');commandInput.setAttribute('aria-expanded','false');commandInput.setAttribute('aria-autocomplete','list');commandInput.setAttribute('aria-controls','command-results');
  commandSearch.append(commandInput,el('kbd','esc'));const commandList=el('div',undefined,'command-list');commandList.id='command-results';commandList.setAttribute('role','listbox');commandList.setAttribute('aria-label','导航结果');
  const commandFooter=el('div',undefined,'command-footer');commandFooter.append(el('span','↑ ↓ 选择'),el('span','↵ 打开'),el('span','esc 关闭'));commandDialog.append(commandSearch,commandList,commandFooter);document.body.append(commandDialog);
  let commands=[],selectedCommand=0;
  function allCommands(){
    const pages=Object.entries(viewLabels).filter(([key])=>key!=='monitor'||state.monitorAllowed).map(([key,label],index)=>({label,icon:key,hint:`${modifier}${index+1}`,keywords:key,action:()=>{setView(key);$('#nav-'+key).focus({preventScroll:true});}}));
    return [...pages,{label:'添加模拟器',icon:'plus',hint:'操作',keywords:'add device',action:openAdd},{label:'新建任务方案',icon:'profiles',hint:'操作',keywords:'new profile',action:()=>{setView('profiles');openProfileEditor();}},...state.devices.map(device=>({label:device.name,icon:'devices',hint:'模拟器',keywords:device.address,action:()=>{setView('devices');$('#search').value='';state.filter='all';for(const b of $$('.filter'))b.classList.toggle('active',b.dataset.filter==='all');render();const card=$(`[data-id="${CSS.escape(device.id)}"]`,$('#devices'));if(card){card.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});card.classList.add('command-highlight');setTimeout(()=>card.classList.remove('command-highlight'),1700);}}}))];
  }
  function renderCommands(){
    const query=commandInput.value.trim().toLowerCase();commands=allCommands().filter(c=>(c.label+' '+c.keywords).toLowerCase().includes(query));selectedCommand=0;commandList.replaceChildren();
    if(!commands.length){commandList.append(el('p','没有找到匹配的页面或实例','command-empty'));commandInput.removeAttribute('aria-activedescendant');return;}
    commands.forEach((command,index)=>{const option=button('','command-option',()=>runCommand(index));option.id='command-option-'+index;option.tabIndex=-1;option.setAttribute('role','option');option.setAttribute('aria-selected',String(index===0));option.append(icon(command.icon).firstChild,el('span',command.label),el('small',command.hint));commandList.append(option);});
    commandInput.setAttribute('aria-activedescendant','command-option-0');
  }
  function openCommands(){if($('#shell').hidden)return;if(commandDialog.open){commandDialog.close();return;}if($('dialog[open]'))return;commandInput.value='';renderCommands();commandDialog.showModal();commandInput.setAttribute('aria-expanded','true');commandInput.focus();}
  function runCommand(index){const command=commands[index];if(!command)return;commandDialog.close();command.action();}
  commandDialog.addEventListener('close',()=>commandInput.setAttribute('aria-expanded','false'));
  commandDialog.addEventListener('pointerdown',event=>{if(event.target!==commandDialog)return;const r=commandDialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)commandDialog.close();});
  commandInput.addEventListener('input',renderCommands);
  commandInput.addEventListener('keydown',event=>{if(event.isComposing)return;if(event.key==='Enter'){event.preventDefault();runCommand(selectedCommand);}else if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();if(!commands.length)return;selectedCommand=(selectedCommand+(event.key==='ArrowDown'?1:-1)+commands.length)%commands.length;for(const [index,option] of [...commandList.children].entries())option.setAttribute('aria-selected',String(index===selectedCommand));commandInput.setAttribute('aria-activedescendant','command-option-'+selectedCommand);commandList.children[selectedCommand].scrollIntoView({block:'nearest'});}});
  document.addEventListener('keydown',event=>{
    if(event.isComposing||event.altKey||(!event.metaKey&&!event.ctrlKey)||$('#shell').hidden)return;
    const key=event.key.toLowerCase();
    if(key==='s'&&$('#config-dialog').open){event.preventDefault();if(!$('#save-profile').disabled)$('#save-profile').click();return;}
    if(key==='k'&&(!$('dialog[open]')||commandDialog.open)){event.preventDefault();openCommands();return;}
    if($('dialog[open]'))return;
    if(/^[1-5]$/.test(key)){const view=Object.keys(viewLabels)[Number(key)-1];if(view==='monitor'&&!state.monitorAllowed)return;event.preventDefault();setView(view);$('#nav-'+view).focus({preventScroll:true});}
  });

  const taskPreview=el('dialog');taskPreview.id='workspace-task-dialog';taskPreview.setAttribute('aria-labelledby','workspace-task-title');
  const previewHeading=el('div',undefined,'dialog-heading');const previewTitle=el('h2');previewTitle.id='workspace-task-title';const previewClose=button('×','icon-button',()=>taskPreview.close());previewClose.setAttribute('aria-label','关闭');previewClose.setAttribute('data-close','workspace-task-dialog');previewHeading.append(previewTitle,previewClose);
  const previewDescription=el('pre',undefined,'description');const previewActions=el('div',undefined,'dialog-actions');const previewCancel=button('关闭','secondary',()=>taskPreview.close());let previewTask=null;
  previewActions.append(previewCancel);taskPreview.append(previewHeading,previewDescription,previewActions);document.body.append(taskPreview);
  let workspaceSignature='',draggingTask=null,dragEndedAt=0,movingTask=false;
  function clearDragStyles(){for(const group of $$('.workspace-task-group'))group.classList.remove('is-drop-target');for(const tile of $$('.workspace-task-tile'))tile.classList.remove('is-insert-before','is-dragging');}
  function makeTaskDraggable(tile,task){
    // Pointer capture keeps dragging consistent over SVG icons, text and empty groups.
    tile.draggable=false;
    let pointer=null,ghost=null,frame=null,dropGroup=null,dropBefore=null;
    function locate(){
      clearDragStyles();tile.classList.add('is-dragging');
      const hit=document.elementFromPoint(pointer.x,pointer.y);
      dropGroup=hit?.closest('.workspace-task-group')||null;
      const target=hit?.closest('.workspace-task-tile');
      dropBefore=target?.dataset.task||null;
      if(dropGroup)dropGroup.classList.add('is-drop-target');
      if(target&&dropBefore!==task.name)target.classList.add('is-insert-before');
      if(ghost){ghost.style.left=(pointer.x+12)+'px';ghost.style.top=(pointer.y+12)+'px';}
    }
    function autoscroll(){
      if(!pointer||!ghost)return;
      const delta=pointer.y>innerHeight-55?12:pointer.y<115?-12:0;
      if(delta){window.scrollBy(0,delta);locate();}
      frame=requestAnimationFrame(autoscroll);
    }
    function finish(commit){
      if(!pointer)return;
      const active=!!ghost,category=dropGroup?.dataset.category,before=dropBefore;
      const id=pointer.id;pointer=null;
      if(frame)cancelAnimationFrame(frame);frame=null;
      ghost?.remove();ghost=null;
      if(active)dragEndedAt=Date.now();draggingTask=null;clearDragStyles();
      try{tile.releasePointerCapture(id);}catch{}
      if(commit&&active&&category&&before!==task.name)moveWorkspaceTask(task.name,category,before);
    }
    tile.addEventListener('dragstart',event=>event.preventDefault());
    tile.addEventListener('pointerdown',event=>{
      if(event.button!==0||movingTask||pointer)return;
      if(event.pointerType==='touch'&&!event.target.closest('.task-drag-handle'))return;
      pointer={id:event.pointerId,startX:event.clientX,startY:event.clientY,x:event.clientX,y:event.clientY};
      tile.setPointerCapture(event.pointerId);
    });
    tile.addEventListener('pointermove',event=>{
      if(!pointer||event.pointerId!==pointer.id)return;
      pointer.x=event.clientX;pointer.y=event.clientY;
      if(!ghost&&Math.hypot(pointer.x-pointer.startX,pointer.y-pointer.startY)<6)return;
      event.preventDefault();
      if(!ghost){
        draggingTask=task.name;
        const rect=tile.getBoundingClientRect();ghost=tile.cloneNode(true);ghost.className='task-drag-ghost';ghost.removeAttribute('data-task');ghost.setAttribute('aria-hidden','true');ghost.tabIndex=-1;ghost.style.width=rect.width+'px';document.body.append(ghost);autoscroll();
      }
      locate();
    });
    tile.addEventListener('pointerup',()=>finish(true));
    tile.addEventListener('pointercancel',()=>finish(false));
    tile.addEventListener('lostpointercapture',()=>{if(pointer)finish(false);});
  }
  async function moveWorkspaceTask(name,category,before=null){
    if(movingTask)return;
    movingTask=true;
    const restoreFocus=document.activeElement?.dataset.task===name;
    try{
      const catalog=await api('catalog/task-category',{method:'PUT',body:JSON.stringify({name,category,before})});
      state.catalog=catalog;workspaceSignature='';renderWorkspaceLibrary();
      if(restoreFocus){const tile=$(`.workspace-task-tile[data-task="${CSS.escape(name)}"]`);if(tile){tile.focus({preventScroll:true});tile.scrollIntoView({block:'nearest'});}}
      if($('#config-dialog').open)renderLibrary();
      toast(`已将“${name}”移到${category}`);
    }catch(error){toast('移动失败：'+error.message);}
    finally{movingTask=false;}
  }
  function renderWorkspaceLibrary(){
    if(!state.catalog)return;
    const search=$('#workspace-task-search').value.trim().toLowerCase();const signature=JSON.stringify([search,state.catalog.tasks]);if(signature===workspaceSignature)return;workspaceSignature=signature;
    $('#workspace-task-count').textContent=state.catalog.tasks.length+' 项';const host=$('#workspace-task-categories');host.replaceChildren();let count=0;
    const categorySymbols={'个人日常':'book','组队日常':'team','周常':'calendar','日常功能':'bag','养成服务':'spark'};
    const categories=state.catalog.categories||Object.keys(categorySymbols);
    for(const category of categories){
      const all=state.catalog.tasks.filter(t=>(t.category||'日常功能')===category).sort((a,b)=>(a.category_order??999)-(b.category_order??999));
      const tasks=all.filter(t=>t.name.toLowerCase().includes(search));count+=tasks.length;
      const group=el('section',undefined,'workspace-task-group');group.dataset.category=category;const heading=el('h3',category);heading.append(el('small',all.length+' 个任务'));group.append(heading);const tiles=el('div',undefined,'workspace-task-tiles');
      for(const task of tasks){
        const tile=button('','workspace-task-tile',async()=>{if(draggingTask||Date.now()-dragEndedAt<300)return;previewTask=task;previewTitle.textContent=task.name;previewDescription.textContent='正在读取任务说明…';if(!taskPreview.open)taskPreview.showModal();try{const result=await api('description?name='+encodeURIComponent(task.name));if(previewTask===task)previewDescription.textContent=result.text;}catch(error){if(previewTask===task)previewDescription.textContent='任务说明暂不可用：'+error.message;}});
        tile.dataset.task=task.name;makeTaskDraggable(tile,task);tile.setAttribute('aria-keyshortcuts','Alt+ArrowLeft Alt+ArrowRight Alt+ArrowUp Alt+ArrowDown');
        tile.addEventListener('keydown',event=>{if(!event.altKey||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key))return;event.preventDefault();if(movingTask)return;const index=all.findIndex(t=>t.name===task.name);if(event.key==='ArrowLeft'||event.key==='ArrowRight'){const next=categories[categories.indexOf(category)+(event.key==='ArrowRight'?1:-1)];if(next)moveWorkspaceTask(task.name,next);}else if(event.key==='ArrowUp'&&index>0)moveWorkspaceTask(task.name,category,all[index-1].name);else if(event.key==='ArrowDown'&&index<all.length-1)moveWorkspaceTask(task.name,category,all[index+2]?.name||null);});
        const symbol=icon(categorySymbols[category]);symbol.className='task-tile-icon';
        if(taskIcons[task.name]){
          const image=el('img');image.src=taskIcons[task.name].url;image.alt='';image.loading='lazy';image.draggable=false;
          image.addEventListener('error',()=>{symbol.classList.remove('is-game-icon');symbol.replaceChildren(icon(categorySymbols[category]).firstChild);},{once:true});
          symbol.classList.add('is-game-icon');symbol.replaceChildren(image);
        }
        const handle=el('span','⠿','task-drag-handle');handle.setAttribute('aria-hidden','true');tile.append(symbol,el('span',task.name),handle);tile.title=task.name+'：点击查看说明；拖动可调整分类和顺序（也可使用 Alt + 方向键）';tiles.append(tile);
      }
      if(!tasks.length)tiles.append(el('p',search?'没有匹配任务，仍可拖入':'将任务拖到这里','task-drop-empty'));
      group.append(tiles);host.append(group);
    }
    if(!count&&search)host.prepend(el('div','没有匹配的任务','command-empty'));
  }
  $('#workspace-task-search').addEventListener('input',renderWorkspaceLibrary);

  let identityRecords=[],identityAt=0,identityLoading=false;
  async function loadFleetIdentity(){
    if(identityLoading||Date.now()-identityAt<60000||(!state.token&&state.authRequired))return;
    identityLoading=true;identityAt=Date.now();
    try{const result=await api('accounts');identityRecords=result.accounts||[];enhanceFleet();}catch{/* Cached role data is optional; device controls keep working. */}finally{identityLoading=false;}
  }
  function enhanceFleet(){
    if(state.view!=='devices')return;
    const records=typeof accountUI!=='undefined'&&accountUI.records.length?accountUI.records:identityRecords;
    for(const device of state.devices){
      const card=$(`[data-id="${CSS.escape(device.id)}"]`,$('#devices'));if(!card)continue;
      const record=records.find(r=>r.device_id===device.id);const identity=record?.sections?.identity?.data||{};
      let avatar=$('.fleet-avatar',card);if(!avatar){avatar=el('div',undefined,'fleet-avatar');avatar.setAttribute('aria-hidden','true');$('.card-head',card).insertBefore(avatar,$('.card-title',card));}
      const fallback=identity.school?.slice(0,1)||device.name.slice(0,1);const avatarSource=record?.avatar_at?'/avatar/'+encodeURIComponent(device.id)+'.png?v='+encodeURIComponent(record.avatar_at):'';
      if(avatar.dataset.source!==avatarSource||(!avatarSource&&avatar.textContent!==fallback)){avatar.dataset.source=avatarSource;avatar.replaceChildren();if(avatarSource){const image=el('img');image.src=avatarSource;image.alt='';image.loading='lazy';image.addEventListener('error',()=>{avatar.textContent=fallback;},{once:true});avatar.append(image);}else avatar.textContent=fallback;}
      const subtitle=$('.card-title p',card);subtitle.title=device.address;subtitle.textContent=identity.role_name?[identity.role_name,identity.level!=null?identity.level+' 级':''].filter(Boolean).join(' · '):(emulatorSpec(device)?.kind==='ldplayer'?'雷电':'MuMu')+' · 实例 '+(emulatorSpec(device)?.index??'ADB');
      let preview=$('.fleet-task-preview',card);if(!preview){preview=el('div',undefined,'fleet-task-preview');$('.card-body',card).append(preview);}
      preview.hidden=!device.tasks.length;
      const signature=JSON.stringify(device.tasks.slice(0,4).map(t=>t.name));if(preview.dataset.signature!==signature){preview.dataset.signature=signature;preview.replaceChildren();for(const task of device.tasks.slice(0,4)){const item=el('div',undefined,'fleet-task-item');item.dataset.task=task.name;item.title=task.name;item.append(el('span',task.name));preview.append(item);}}
      for(const item of preview.children)item.classList.toggle('is-current',!!device.run.active&&device.run.task===item.dataset.task);
    }
  }
  document.addEventListener('app:data',()=>{renderWorkspaceLibrary();enhanceFleet();loadFleetIdentity();});
  document.addEventListener('app:viewchange',event=>{if(event.detail==='devices'){enhanceFleet();loadFleetIdentity();}});
  fetch('/static/task-icons/manifest.json',{cache:'no-store'}).then(response=>{if(!response.ok)throw new Error('icons unavailable');return response.json();}).then(icons=>{taskIcons=icons;workspaceSignature='';renderWorkspaceLibrary();}).catch(()=>{});
  renderWorkspaceLibrary();enhanceFleet();loadFleetIdentity();
})();
