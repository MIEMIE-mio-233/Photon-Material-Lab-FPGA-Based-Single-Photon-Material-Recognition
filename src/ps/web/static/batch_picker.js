/* 数据与训练共用同一套批次筛选。筛选只改变列表，不修改标签或隐式取消勾选。 */
'use strict';
function batchDate(run) {
  const match = /run_(\d{4})(\d{2})(\d{2})_/.exec(run.id || run.key || '');
  return match ? `${match[1]}-${match[2]}-${match[3]}` : '';
}
function newestRuns(runs) { return [...runs].sort((a,b) => (b.id || b.key).localeCompare(a.id || a.key)); }
function batchMatches(run, filter) {
  const materials = run.materials || [run.material];
  const haystack = [run.id,run.specimen,...materials].join(' ').toLowerCase();
  return (!filter.search || haystack.includes(filter.search.toLowerCase())) &&
    (!filter.date || batchDate(run) === filter.date) &&
    (!filter.material || materials.includes(filter.material)) &&
    (!filter.specimen || run.specimen === filter.specimen) &&
    (!filter.light || (filter.light==='unknown' ? !run.illumination : run.illumination===filter.light)) &&
    (!filter.distance || (filter.distance==='unknown' ? run.distance_cm==null : Number(run.distance_cm)===Number(filter.distance)));
}
function readBatchFilter(prefix) {
  return Object.fromEntries(['Search','Date','Material','Specimen','Light','Distance'].map(key =>
    [key.toLowerCase(), $(prefix+key).value.trim()]));
}
function filteredBatchRuns(prefix, runs) { const filter=readBatchFilter(prefix); return newestRuns(runs).filter(run=>batchMatches(run,filter)); }
function setFilterOptions(id, values, title) {
  const field=$(id), previous=field.value;
  field.replaceChildren(new Option(title,''));
  [...new Set(values.filter(value=>value!=null && value!==''))].sort((a,b)=>String(a).localeCompare(String(b),'zh-CN',{numeric:true}))
    .forEach(value=>field.appendChild(new Option(String(value),String(value))));
  if ([...field.options].some(option=>option.value===previous))field.value=previous;
}
function refreshBatchFilters() {
  for (const [prefix,runs] of [['dataBatch',dataset.runs],['trainBatch',trainableRuns()]]) {
    setFilterOptions(prefix+'Material',runs.flatMap(run=>run.materials||[run.material]),'全部材质');
    setFilterOptions(prefix+'Specimen',runs.map(run=>run.specimen),'全部实物');
    const known=runs.map(run=>run.distance_cm).filter(value=>value!=null);
    const previousDistance=$(prefix+'Distance').value;
    setFilterOptions(prefix+'Distance',known,'全部距离');
    if(runs.some(run=>run.distance_cm==null)) {
      $(prefix+'Distance').appendChild(new Option('未记录','unknown'));
      if(previousDistance==='unknown')$(prefix+'Distance').value='unknown';
    }
  }
}
function updateDataBatchSummary() {
  const run=dataset.runs.find(item=>item.key===$('runSelect').value);
  $('dataBatchSummary').textContent=run ? `${run.material} · ${run.specimen} · ${batchDate(run)} · ${run.frames}帧` : '全部筛选批次';
}
function renderDataBatchList() {
  const runs=filteredBatchRuns('dataBatch',dataset.runs), list=$('dataBatchResults');
  list.replaceChildren();
  if($('runSelect').value && !runs.some(run=>run.key===$('runSelect').value))$('runSelect').value='';
  const choose=(key)=>{ $('runSelect').value=key; updateDataBatchSummary();
    $('dataBatchPicker').open=false; $('runSelect').dispatchEvent(new Event('change')); };
  const all=document.createElement('button');all.type='button';all.className='batch-result';all.textContent=`全部筛选批次 · ${runs.length} 批`;
  all.addEventListener('click',()=>choose(''));list.appendChild(all);
  for(const run of runs) {
    const button=document.createElement('button');button.type='button';button.className='batch-result';
    button.classList.toggle('selected',run.key===$('runSelect').value);
    const title=document.createElement('strong');title.textContent=`${(run.materials||[run.material]).join(' / ')} · ${run.specimen} · ${run.frames} 帧`;
    const clock=/run_\d{8}_(\d{2})(\d{2})(\d{2})/.exec(run.id||run.key||'');
    const time=clock?` ${clock[1]}:${clock[2]}:${clock[3]}`:'';
    const detail=document.createElement('span');detail.textContent=`${batchDate(run)}${time} · ${run.distance_cm??'—'} cm · ${illuminationName(run.illumination)}`;
    button.title=run.id;button.append(title,detail);button.addEventListener('click',()=>choose(run.key));list.appendChild(button);
  }
  if(!runs.length){const empty=document.createElement('p');empty.className='muted';empty.textContent='没有匹配的批次';list.appendChild(empty);}
  updateDataBatchSummary();
}
function applyBatchFilters(prefix) {
  if(prefix==='trainBatch') { renderTrainingRuns();renderDisabled();return; }
  renderDataBatchList();fillFrames();
  if(panel==='data' && dataDisplayMode==='single')showSelectedDataFrame();
}
function initializeBatchPickers() {
  for(const prefix of ['dataBatch','trainBatch']) {
    let searchTimer;
    for(const key of ['Search','Date','Material','Specimen','Light','Distance'])
      $(prefix+key).addEventListener(key==='Search'?'input':'change',()=>{
        if(key==='Search'){clearTimeout(searchTimer);searchTimer=setTimeout(()=>applyBatchFilters(prefix),180);}
        else applyBatchFilters(prefix);
      });
    $(prefix+'Reset').addEventListener('click',()=>{
      ['Search','Date','Material','Specimen','Light','Distance'].forEach(key=>$(prefix+key).value='');applyBatchFilters(prefix);
    });
  }
}
function renderBatchPickerControls(isBusy) {
  for(const prefix of ['dataBatch','trainBatch'])
    ['Search','Date','Material','Specimen','Light','Distance','Reset'].forEach(key=>$(prefix+key).disabled=isBusy);
  document.querySelectorAll('#dataBatchResults button').forEach(button=>button.disabled=isBusy);
}
