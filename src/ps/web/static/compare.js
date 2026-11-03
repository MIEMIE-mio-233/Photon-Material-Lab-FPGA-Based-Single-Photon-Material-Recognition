/* 多帧对比：浏览器保留最多4个待选文件，PS逐帧读取/识别，网页统一叠加展示。 */
'use strict';
const COMPARE_COLORS = ['#58d3cb', '#c6ed87', '#edc06c', '#bba1f3'];
let selectedCompareFrames = [], comparisonPlot = null, comparisonView = 'full';
let comparisonSignature = '', comparisonPlotRequest = 0, dataDisplayMode = 'single';
let comparisonLayout='overlay';

function frameCaption(path) { return path.split('/').slice(-2).join(' / '); }

function updateComparisonVisibility() {
  $('singleFrameControls').classList.toggle('hidden', dataDisplayMode !== 'single');
  $('singleBatchManagement').classList.toggle('hidden', dataDisplayMode !== 'single');
  $('multiFrameControls').classList.toggle('hidden', dataDisplayMode !== 'compare');
  $('comparisonWorkspace').classList.toggle('hidden', dataDisplayMode !== 'compare');
  $('workspace').classList.toggle('hidden', !['capture', 'data'].includes(panel) || (panel === 'data' && dataDisplayMode !== 'single'));
  document.querySelectorAll('.data-mode').forEach(button => {
    const selected = button.dataset.mode === dataDisplayMode;
    button.classList.toggle('active', selected); button.setAttribute('aria-pressed', String(selected));
  });
  $('framePickerLabel').textContent = dataDisplayMode === 'single' ? '单帧文件' : '待加入的文件';
}
function setDataDisplayMode(mode) {
  if (!['single', 'compare'].includes(mode)) return;
  dataDisplayMode = mode;
  updateComparisonVisibility();
  renderDisabled();
  if (mode === 'compare') requestAnimationFrame(drawComparisonChart);
  else if (panel === 'data') restoreSingleDataView();
}
function renderCompareDisabled(isBusy) {
  const path = $('frameSelect').value;
  $('addCompare').disabled = isBusy || !path || selectedCompareFrames.length >= 4 || selectedCompareFrames.some(item => item.path === path);
  $('clearCompare').disabled = isBusy || !selectedCompareFrames.length;
  ['plotCompare', 'recognizeCompare'].forEach(id => { $(id).disabled = isBusy || !selectedCompareFrames.length; });
  $('compareBackend').disabled = isBusy;
  $('plotFile').disabled = isBusy || !path;
  $('recognizeFile').disabled = isBusy || !path || !state?.model?.available;
  document.querySelectorAll('.compare-remove').forEach(button => { button.disabled = isBusy; });
}
function renderCompareSelection() {
  $('compareSelectionCount').textContent = `${selectedCompareFrames.length} / 4 帧`;
  $('compareSelected').replaceChildren();
  if (!selectedCompareFrames.length) {
    const hint = document.createElement('span'); hint.className = 'muted';
    hint.textContent = '选择文件后点击“加入所选帧”，支持跨批次选择，最多4帧。';
    $('compareSelected').appendChild(hint);
  }
  selectedCompareFrames.forEach((item, index) => {
    const chip = document.createElement('div'); chip.className = 'compare-chip';
    const dot = document.createElement('i'); dot.style.background = COMPARE_COLORS[index];
    const title = document.createElement('span'); title.textContent = `${index + 1}. ${frameCaption(item.path)}`; title.title = item.path;
    const remove = document.createElement('button'); remove.className = 'compare-remove'; remove.textContent = '移除';
    remove.setAttribute('aria-label', '移除 ' + frameCaption(item.path));
    remove.addEventListener('click', () => { selectedCompareFrames.splice(index, 1); renderCompareSelection(); });
    chip.append(dot, title, remove); $('compareSelected').appendChild(chip);
  });
  renderDisabled();
}
function addSelectedComparison() {
  const path = $('frameSelect').value;
  if (!path) return toast('请先选择一帧文件', true);
  if (selectedCompareFrames.some(item => item.path === path)) return toast('该帧已经加入对比');
  if (selectedCompareFrames.length >= 4) return toast('最多同时对比4帧，请先移除一帧', true);
  selectedCompareFrames.push({path}); renderCompareSelection();
}
function removeDeletedComparison(prefix) {
  selectedCompareFrames = selectedCompareFrames.filter(item => !item.path.startsWith(prefix + '/'));
  renderCompareSelection();
}

function renderComparisonRows(comparison) {
  const rows = comparison ? comparison.frames : [];
  $('compareScoreHeader').textContent = rows.some(row => row.result?.score_kind === 'normalized_margin') ? '归一化决策分数' : '参考分数';
  $('compareRows').replaceChildren();
  if (!rows.length) {
    const row = document.createElement('tr'), cell = document.createElement('td');
    cell.colSpan = 10; cell.className = 'muted'; cell.textContent = '等待对比结果'; row.appendChild(cell); $('compareRows').appendChild(row);
  }
  rows.forEach((item, index) => {
    const row = document.createElement('tr'), file = document.createElement('td');
    const marker = document.createElement('i'); marker.className = 'compare-dot'; marker.style.background = COMPARE_COLORS[index];
    const label = document.createElement('strong'); label.textContent = item.path.split('/').pop(); label.title = item.path;
    const folder = document.createElement('small'); folder.textContent = item.path.split('/').slice(-3, -1).join(' / ');
    file.append(marker, label, folder); row.appendChild(file);
    const result = item.result;
    const score = result && Object.keys(result.class_scores).length ? (Math.max(...Object.values(result.class_scores)) * 100).toFixed(1) + '%' : '—';
    const values = [result ? result.material : '—', score, Number.isFinite(result?.estimated_distance_cm)?result.estimated_distance_cm.toFixed(2):'—',item.reference_bin ?? '—', item.return_bin ?? '—', item.total_counts ?? '—', formatMilliseconds(result?.elapsed_ms), formatMilliseconds(result?.compute_ms), item.error || (result?.valid_signal===false?'无有效回波':result ? '已识别' : '仅波形')];
    values.forEach((value, column) => {
      const cell = document.createElement('td'); cell.textContent = String(value);
      if (column === values.length-1 && item.error) cell.className = 'comparison-error';
      row.appendChild(cell);
    });
    $('compareRows').appendChild(row);
  });
  const model = rows.find(item => item.result)?.result.model_id;
  $('compareInfo').textContent = comparison ? `${comparison.recognize ? (comparison.backend === 'pl' ? 'PL 加速识别' : 'PS CPU 识别') : '仅对比波形'} · ${rows.length} 帧${model ? ' · 模型 ' + model : ''}` : '尚未开始';
  renderComparisonFeatures(rows);
}
function renderComparisonFeatures(rows) {
  const head=$('featureCompareHead'),body=$('featureCompareRows');head.replaceChildren();body.replaceChildren();
  $('comparisonFeatures').classList.toggle('hidden',!rows.some(row=>row.metrics));
  if(!rows.length)return;
  const heading=document.createElement('tr');const title=document.createElement('th');title.textContent='特征';heading.appendChild(title);
  rows.forEach((row,i)=>{const cell=document.createElement('th');cell.textContent=`第${i+1}帧`;cell.style.color=COMPARE_COLORS[i];cell.title=row.path;heading.appendChild(cell);});head.appendChild(heading);
  const fields=[['return_bin','回波峰位 / bin',0],['peak_gap_bins','前后峰间距 / bin',0],['peak_ratio','回波/参考峰高比',4],
    ['area_ratio','回波/参考面积比',4],['half_width_bins','半高宽 / bin',1],['weighted_sigma_bins','加权宽度 / bin',1]];
  for(const [key,label,digits]of fields) {
    const tr=document.createElement('tr'),name=document.createElement('th');name.textContent=label;tr.appendChild(name);
    const values=rows.map(row=>row.metrics?.[key]),max=Math.max(...values.filter(Number.isFinite),1e-9),base=values[0];
    values.forEach((value,i)=>{
      const td=document.createElement('td');if(!Number.isFinite(value)){td.textContent='—';tr.appendChild(td);return;}
      const main=document.createElement('strong');main.textContent=value.toFixed(digits);
      const difference=document.createElement('span');difference.className='feature-difference';
      if(i && Number.isFinite(base)){const delta=value-base;difference.textContent=`${delta>=0?'+':''}${delta.toFixed(digits)}`;}
      td.append(main,difference);
      if(key!=='return_bin'&&key!=='peak_gap_bins') {
        const bar=document.createElement('div');bar.className='feature-mini-bar';bar.style.width=`${Math.max(0,value/max)*100}%`;bar.style.background=COMPARE_COLORS[i];td.appendChild(bar);
      }
      tr.appendChild(td);
    });body.appendChild(tr);
  }
}
function clearComparisonPlot() {
  comparisonPlot = null; comparisonPlotRequest += 1;
  const canvas = $('compareHistogram'); canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
  $('compareSmallMultiples').replaceChildren();
  $('comparePlaceholder').classList.remove('hidden'); $('compareLegend').replaceChildren();
}
function updateComparisonState() {
  const comparison = state.comparison;
  const signature = comparison ? `${comparison.id}:${comparison.frames.length}` : '';
  if (signature === comparisonSignature) return;
  const previousId = comparisonSignature.split(':')[0]; comparisonSignature = signature;
  renderComparisonRows(comparison);
  if (!comparison || comparison.id !== previousId) clearComparisonPlot();
  // 后台完成或页面轮询只更新结果，不擅自切换用户选定的查看模式。
  if (comparison && comparison.frames.length) loadComparisonPlot();
}
async function loadComparisonPlot() {
  const id = state && state.comparison && state.comparison.id;
  if (!id) return;
  const request = ++comparisonPlotRequest, requestedView = comparisonView;
  try {
    const result = await api('/api/comparison/plot?view=' + requestedView);
    // 旧请求或旧批次响应不能覆盖用户刚切换的视图。
    if (request !== comparisonPlotRequest || requestedView !== comparisonView || result.id !== state.comparison?.id) return;
    comparisonPlot = result; $('comparePlaceholder').classList.add('hidden');
    $('compareRange').textContent = result.view === 'full' ? '完整图：线性纵轴 0–500 · 各帧共用坐标轴' : '回波区域：覆盖各帧回波峰 · 线性纵轴自动范围';
    $('compareLegend').replaceChildren();
    result.curves.forEach(curve => {
      const label = document.createElement('span'), dot = document.createElement('i');
      dot.style.background = COMPARE_COLORS[curve.index]; label.title = curve.path;
      label.append(dot, document.createTextNode(`${curve.index + 1}. ${frameCaption(curve.path)}`)); $('compareLegend').appendChild(label);
    });
    requestAnimationFrame(drawComparisonChart);
  } catch (error) {
    if (request !== comparisonPlotRequest) return;
    clearComparisonPlot(); toast(error.message, true);
  }
}
function drawComparisonChart() {
  const plot=comparisonPlot;
  const split=comparisonLayout==='split' && !!plot;
  $('compareOverlayWrap').classList.toggle('hidden',split);
  $('compareSmallMultiples').classList.toggle('hidden',!split);
  if(!plot)return;
  if(comparisonLayout==='split') {
    const grid=$('compareSmallMultiples');grid.replaceChildren();
    plot.curves.forEach(curve=>{
      const card=document.createElement('section');card.className='compare-mini';
      const title=document.createElement('strong');title.textContent=`第${curve.index+1}帧 · ${frameCaption(curve.path)}`;title.style.color=COMPARE_COLORS[curve.index];
      const canvas=document.createElement('canvas');canvas.setAttribute('aria-label',`第${curve.index+1}帧波形`);card.append(title,canvas);grid.appendChild(card);
      drawComparisonCanvas(canvas,plot,[curve]);
    });
  }else drawComparisonCanvas($('compareHistogram'),plot,plot.curves);
}
function drawComparisonCanvas(canvas,plot,curves) {
  if (!canvas.clientWidth || !plot) return;
  const ratio = window.devicePixelRatio || 1, width = canvas.clientWidth, height = canvas.clientHeight;
  canvas.width = width * ratio; canvas.height = height * ratio;
  const ctx = canvas.getContext('2d'); ctx.scale(ratio, ratio);
  const left = 48, top = 16, right = width - 17, bottom = height - 35;
  const px = value => left + (value - plot.x_min) / Math.max(1, plot.x_max - plot.x_min) * (right - left);
  const py = value => bottom - Math.min(value, plot.y_max) / plot.y_max * (bottom - top);
  ctx.font = '10px Segoe UI, sans-serif'; ctx.lineWidth = 1;
  for (let i = 0; i <= 5; i++) {
    const y = top + (bottom - top) * i / 5;
    ctx.strokeStyle = '#28363e'; ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y); ctx.stroke();
    ctx.fillStyle = '#79909a'; ctx.textAlign = 'right'; ctx.fillText(String(Math.round(plot.y_max * (5 - i) / 5)), left - 9, y + 3);
    const x = left + (right - left) * i / 5;
    ctx.textAlign = 'center'; ctx.fillText(String(Math.round(plot.x_min + (plot.x_max - plot.x_min) * i / 5)), x, bottom + 18);
  }
  ctx.fillStyle = '#8298a2'; ctx.textAlign = 'left'; ctx.fillText('计数', 3, 10);
  ctx.textAlign = 'right'; ctx.fillText('bin 位置', right, height - 3);
  ctx.save(); ctx.beginPath(); ctx.rect(left, top, right - left, bottom - top); ctx.clip();
  curves.forEach(curve => {
    ctx.beginPath(); curve.x.forEach((x, index) => { if (!index) ctx.moveTo(px(x), py(curve.y[index])); else ctx.lineTo(px(x), py(curve.y[index])); });
    ctx.strokeStyle = COMPARE_COLORS[curve.index]; ctx.lineWidth = 1.35; ctx.stroke();
  });
  ctx.restore();
}
function initializeComparison() {
  document.querySelectorAll('.data-mode').forEach(button => button.addEventListener('click', () => setDataDisplayMode(button.dataset.mode)));
  updateComparisonVisibility();
  $('addCompare').addEventListener('click', addSelectedComparison);
  $('clearCompare').addEventListener('click', () => { selectedCompareFrames = []; renderCompareSelection(); });
  $('frameSelect').addEventListener('change', renderDisabled);
  $('compareBackend').addEventListener('change', () => action('/api/hardware', {action: $('compareBackend').value}));
  for (const [id, recognize] of [['plotCompare', false], ['recognizeCompare', true]]) {
    $(id).addEventListener('click', () => {
      if (!selectedCompareFrames.length || selectedCompareFrames.length > 4) return toast('请选择1至4帧', true);
      action('/api/jobs/compare', {paths: selectedCompareFrames.map(item => item.path), recognize});
    });
  }
  document.querySelectorAll('.compare-view').forEach(button => button.addEventListener('click', () => {
    comparisonView = button.dataset.view;
    document.querySelectorAll('.compare-view').forEach(item => item.classList.toggle('active', item === button));
    loadComparisonPlot();
  }));
  window.addEventListener('resize', drawComparisonChart);
  document.querySelectorAll('.compare-layout').forEach(button=>button.addEventListener('click',()=>{
    comparisonLayout=button.dataset.layout;
    document.querySelectorAll('.compare-layout').forEach(item=>{item.classList.toggle('active',item===button);item.setAttribute('aria-pressed',String(item===button));});
    drawComparisonChart();
  }));
}
