/* 离线原生 JavaScript：PS提供网页，计算可选择PS或PL。 */
'use strict';
const $ = id => document.getElementById(id);
let state = null, dataset = {frames: [], runs: []}, panel = 'output', view = 'full';
let chart = null, displayedPath = null, latestSignature = '', figure = 'overview', trainingSignature = '', busyRequest = false;
let selectedUpload = null, toastTimer = null, dataSignature = '', logSignature = '';
let outputRequest = false, outputToggleRequest = false, outputFieldsLoaded = false;
let thresholdFieldsLoaded = false;
const illuminationName = value => ({shielded:'遮光', partial:'半遮光', exposed:'暴露'})[value] || '光照未标注';
let singleDataFrame = null, singleDataChart = null;
let pollRequest = null, cycleTimer = null;
let dataDirty = false;
let dataRequest = null, figureRequest = 0, figureAbort = null, figureObjectUrl = null;
// 只缓存正在浏览的模型的最近3幅图，不加载其他模型参数；大图只保留当前一幅。
const figureCache = new Map(), FIGURE_CACHE_BYTES = 2 * 1024 * 1024;
let figureCacheVersion = '', figureCacheBytes = 0, figurePending = null;
// 仅在同一文件、同一模型下比较最近的PS/PL结果，不跨样本计算加速比。
const timingComparisons = new Map();
function formatMilliseconds(value) { return Number.isFinite(value) ? value.toFixed(3) + ' ms' : '—'; }
function displayTiming(frame) {
  const result = frame.result;
  $('resultElapsed').textContent = formatMilliseconds(result?.elapsed_ms);
  $('resultCompute').textContent = formatMilliseconds(result?.compute_ms);
  $('timingComparison').classList.add('hidden');
  if (!result || !Number.isFinite(result.elapsed_ms) || !result.model_id) return;
  const key = JSON.stringify([frame.path, result.model_id]);
  const pair = timingComparisons.get(key) || {};
  pair[result.backend.startsWith('PL') ? 'pl' : 'cpu'] = result;
  timingComparisons.set(key, pair);
  if (timingComparisons.size > 32) timingComparisons.delete(timingComparisons.keys().next().value);
  if (pair.cpu && pair.pl && pair.pl.elapsed_ms > 0) {
    $('timingComparison').textContent = `同帧总耗时比（PS÷PL）：${(pair.cpu.elapsed_ms / pair.pl.elapsed_ms).toFixed(2)}×`;
    $('timingComparison').classList.remove('hidden');
  }
}

function toast(message, error = false) {
  const element = $('toast'); element.textContent = message;
  element.classList.remove('hidden'); element.classList.toggle('error', error);
  clearTimeout(toastTimer); toastTimer = setTimeout(() => element.classList.add('hidden'), error ? 8000 : 4000);
}
async function api(path, body, form = false) {
  const options = body === undefined ? {} : {method: 'POST', body: form ? body : JSON.stringify(body)};
  if (body !== undefined && !form) options.headers = {'Content-Type': 'application/json'};
  const response = await fetch(path, options);
  let result;
  try { result = await response.json(); } catch (_) { throw new Error('服务暂时没有响应，请稍后重试'); }
  if (!response.ok || !result.ok) throw new Error(result.error || '操作未完成');
  return result;
}
function active() { return !!state && ['running', 'stopping'].includes(state.job.status); }
async function action(path, body, options = {}) {
  if (busyRequest) return false;
  busyRequest = true; renderDisabled();
  const restore = buttonProgress(options.button, options.pending || '正在提交…');
  try { await api(path, body); await poll(); if (options.success) toast(options.success); return true; }
  catch (error) { toast(error.message, true); return false; }
  finally { restore(); busyRequest = false; renderDisabled(); schedulePoll(active() ? 200 : 1500); }
}
function renderDisabled() {
  const isBusy = active() || busyRequest;
  for (const id of ['singleCapture', 'batchCapture', 'continuousCapture', 'recognizeFile', 'startTrain', 'modelSource']) $(id).disabled = isBusy;
  ['loadOverlay', 'loadOutputOverlay'].forEach(id => { $(id).disabled = isBusy || !!(state && state.hardware.loaded); });
  $('inferenceBackend').disabled = isBusy;
  ['source', 'frameCount', 'autoRecognize', 'runSelect', 'frameSelect', 'upload', 'refreshData'].forEach(id => { $(id).disabled = isBusy; });
  $('saveData').disabled = isBusy || $('source').value !== 'pl';
  ['material', 'specimen', 'distance', 'sampleKind', 'illumination', 'experimentRound'].forEach(id => { $(id).disabled = isBusy || $('source').value !== 'pl' || !$('saveData').checked; });
  renderCompareDisabled(isBusy);
  renderBatchPickerControls(isBusy);
  $('deleteRun').disabled = isBusy || dataDisplayMode !== 'single' || !$('runSelect').value;
  const outputs = state && state.hardware.outputs;
  $('applyOutputs').disabled = isBusy || outputRequest || outputToggleRequest || !outputs || !outputs.available || outputs.busy;
  const referenceDisabled = isBusy || outputRequest || outputToggleRequest || !outputs || !outputs.available || outputs.enabled || outputs.busy;
  $('applyReference').disabled = referenceDisabled;
  $('referenceSource').disabled = referenceDisabled;
  ['dac1Low', 'dac1High', 'dac2Low', 'dac2High'].forEach(id => { $(id).disabled = referenceDisabled; });
  const thresholdDisabled = referenceDisabled || !outputs?.thresholds?.ready || outputs?.thresholds?.busy;
  ['thresholdA', 'thresholdB', 'applyThresholds'].forEach(id => { $(id).disabled = thresholdDisabled; });
  $('restoreDefaults').disabled = isBusy || outputRequest || outputToggleRequest || !outputs?.available || !!outputs?.thresholds?.busy;
  renderModelControls(isBusy);
  renderRangeControls(isBusy);
  // 开关不受采集任务或一般请求锁阻挡，关闭输出可以随时发到独立AXI寄存器。
  $('toggleOutputs').disabled = outputToggleRequest || !outputs?.available || (!outputs.enabled && !outputs.thresholds?.ready);
  document.querySelectorAll('.stop-button').forEach(button => { button.disabled = !active() || state.job.status === 'stopping'; });
}
function switchPanel(name) {
  panel = name;
  if (name !== 'train' && figurePending) {
    ++figureRequest;
    if (figureAbort) figureAbort.abort();
    figurePending = null;
  }
  ['output', 'capture', 'data', 'train'].forEach(item => $('panel-' + item).classList.toggle('hidden', item !== name));
  document.querySelectorAll('.nav').forEach(button => { button.classList.toggle('active', button.dataset.panel === name); if(button.dataset.panel===name)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current'); });
  updateComparisonVisibility();
  $('captureHistory').classList.toggle('hidden', name !== 'capture');
  if (name === 'data' && dataDisplayMode === 'single') restoreSingleDataView();
  if (name === 'capture' && state && state.latest) { displayResult(state.latest); loadPlot(state.latest.path); }
  if (name === 'data' && dataDisplayMode === 'compare') requestAnimationFrame(drawComparisonChart);
  if (name === 'train') loadFigure(); else if (name !== 'output') requestAnimationFrame(drawChart);
  if ((name === 'data' || name === 'train') && dataDirty) refreshData().catch(error => toast(error.message, true));
}
function updateCaptureLabels() {
  // 只有勾选保存时才显示标签；未勾选的帧仅在内存中用于显示和识别。
  const real = $('source').value === 'pl';
  $('saveDataField').title = real ? '勾选后按批次保存完整帧' : '历史演示读取已有数据，无需再次保存';
  const show = real && $('saveData').checked;
  $('auxiliaryRecords').classList.toggle('hidden', !show);
  ['material', 'specimen', 'distance', 'sampleKind', 'illumination', 'experimentRound'].forEach(id => {
    $(id + 'Field').classList.toggle('hidden', !show);
    $(id).disabled = !show;
  });
}
function updateSource() {
  const real = $('source').value === 'pl';
  updateCaptureLabels();
  $('captureSourceBadge').textContent = real ? '真实 TDC 采集' : '历史数据演示';
  $('captureSourceBadge').classList.toggle('amber', !real);
  renderDisabled();
}
function captureOptions(frames, continuous) {
  const options = {source: $('source').value, frames, continuous, interval_s: 0, recognize: $('autoRecognize').checked};
  options.demo_sync = options.source === 'history';
  options.save_data = options.source === 'pl' && $('saveData').checked;
  if (options.save_data) {
    options.material = $('material').value.trim(); options.specimen = $('specimen').value.trim();
    options.distance_cm = $('distance').value; options.sample_kind = $('sampleKind').value;
    options.illumination = $('illumination').value; options.experiment_round = $('experimentRound').value.trim();
  }
  return options;
}
function fillFrames() {
  const run = $('runSelect').value, previous = $('frameSelect').value;
  const allowed = new Set(filteredBatchRuns('dataBatch',dataset.runs).map(item=>item.key));
  const frames = dataset.frames.filter(item => run ? item.run_key === run : allowed.has(item.run_key))
    .sort((a,b)=>b.run.localeCompare(a.run) || a.frame_index-b.frame_index);
  $('frameSelect').replaceChildren();
  for (const item of frames) {
    const option = document.createElement('option'); option.value = item.path;
    option.textContent = `${item.material === 'unlabeled' ? '未标注' : item.material} / ${item.specimen} / ${item.distance_cm ?? "未知"} cm / frame_${String(item.frame_index).padStart(4, '0')} · ${item.run}`;
    $('frameSelect').appendChild(option);
  }
  if (selectedUpload) {
    const option = document.createElement('option'); option.value = selectedUpload.path;
    option.textContent = '已上传 · ' + selectedUpload.name; $('frameSelect').prepend(option);
  }
  if ([...$('frameSelect').options].some(option => option.value === previous)) $('frameSelect').value = previous;
  if (!$('frameSelect').options.length) $('frameSelect').appendChild(new Option('暂无数据，请上传单帧 CSV', ''));
  updateDataBatchSummary();
  $('selectedPath').textContent = $('frameSelect').value || '暂无数据';
  renderDisabled();
}
function shouldRefreshDataset(data) {
  const signature = `${data.frame_count}:${data.specimen_count}`;
  if (dataSignature && signature !== dataSignature) dataDirty = true;
  dataSignature = signature;
  return dataDirty && !active() && (panel === 'data' || panel === 'train');
}
async function refreshData() {
  if (dataRequest) return dataRequest;
  dataRequest = (async () => {
    dataset = await api('/api/data');
    dataDirty = !!state && (state.dataset.frame_count !== dataset.frame_count || state.dataset.specimen_count !== dataset.specimen_count);
    const previous = $('runSelect').value;
    $('runSelect').replaceChildren(new Option('全部批次', ''));
    for (const run of newestRuns(dataset.runs)) $('runSelect').appendChild(new Option(run.id, run.key));
    if (dataset.runs.some(run => run.key === previous)) $('runSelect').value = previous;
    refreshBatchFilters();renderDataBatchList();fillFrames();renderTrainingRuns();renderDisabled();
  })();
  try { await dataRequest; } finally { dataRequest = null; }
}
function displayResult(frame) {
  const result = frame.result;
  $('resultSource').textContent = ({history: '历史演示', pl: '内部AXI采集', file: '文件识别'})[frame.source] || '文件';
  $('resultSource').classList.toggle('amber', frame.source === 'history');
  $('resultMaterial').textContent = result ? result.material : '—';
  const best = result && Object.keys(result.class_scores).length ? Math.max(...Object.values(result.class_scores)) : null;
  $('resultScore').textContent = result ? `${result.score_kind === 'normalized_margin' ? '归一化决策分数' : '参考分数'} ${(best * 100).toFixed(1)}% · ${result.backend.startsWith('PL') ? result.backend : 'PS CPU'} · 模型 ${result.model_id}` : (frame.error || '已读取直方图，尚未识别');
  displayTiming(frame); renderDistanceResult(result);
  renderFrameStages(frame);
  $('referencePeak').textContent = result ? result.reference_bin : '—';
  $('returnPeak').textContent = result ? result.return_bin : '—';
  $('peakShift').textContent = Number.isFinite(result?.peak_shift_bins) ? result.peak_shift_bins.toFixed(2) : '—';
  $('materialMetric').textContent = result ? result.material : '—';
  $('scoreMetric').textContent = result ? `${result.score_kind === 'normalized_margin' ? '决策分数' : '参考分数'} ${(best * 100).toFixed(1)}% · 第 ${frame.frame_index} 帧` : '等待识别结果';
  $('truth').classList.toggle('hidden', !frame.truth);
  $('truth').textContent = frame.truth ? '历史帧标签：' + frame.truth : '';
  if(result?.valid_signal===false) { $('resultScore').textContent='背景质量检测：未进入材质分类'; $('scoreMetric').textContent='无有效回波'; }
  $('scores').replaceChildren();
  if (result) {
    const rows = Object.entries(result.class_scores).sort((a, b) => b[1] - a[1]).slice(0, 5);
    for (const [name, score] of rows) {
      const row = document.createElement('div'); row.className = 'score-row';
      const label = document.createElement('div'); label.className = 'score-label';
      const title = document.createElement('span'); title.textContent = name;
      const value = document.createElement('span'); value.textContent = (score * 100).toFixed(1) + '%';
      label.append(title, value);
      const track = document.createElement('div'); track.className = 'score-track';
      const bar = document.createElement('div'); bar.style.width = (score * 100) + '%'; track.appendChild(bar);
      row.append(label, track); $('scores').appendChild(row);
    }
  } else { $('scores').textContent = frame.error || '识别后展示各类别分数'; }
  $('downloadFrame').href = '/api/frame/download?path=' + encodeURIComponent(frame.path);
  $('downloadFrame').classList.remove('hidden');
}

function clearFrame() {
  displayedPath = null; chart = null; latestSignature = '';
  const canvas = $('histogram'); canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
  $('chartPlaceholder').classList.remove('hidden'); $('framePath').textContent = '尚未选择数据';
  for (const id of ['resultMaterial', 'referencePeak', 'returnPeak', 'peakShift', 'materialMetric']) $(id).textContent = '—';
  $('resultSource').textContent = '等待数据'; $('resultScore').textContent = '参考分数 —';
  $('scoreMetric').textContent = '等待识别结果'; $('truth').classList.add('hidden');
  displayTiming({result: null}); renderDistanceResult(null);
  renderFrameStages({});
  $('scores').textContent = '识别后展示各类别分数'; $('downloadFrame').classList.add('hidden');
}

function showSingleDataFrame(path) {
  singleDataFrame = {path, source: 'file', frame_index: 1, result: null, error: null};
  singleDataChart = null;
  displayResult(singleDataFrame); loadPlot(path, true);
}
function showSelectedDataFrame() {
  const path=$('frameSelect').value;
  if(path)showSingleDataFrame(path);
  else {singleDataFrame=null;singleDataChart=null;clearFrame();}
}
function restoreSingleDataView() {
  // 数据页的选择独立保留，实时采集结果和多帧轮询不能覆盖它。
  if (!singleDataFrame) {
    showSelectedDataFrame();
    return;
  }
  const saved = dataset.frames.find(item => item.path === singleDataFrame.path);
  // 切回单帧时尊重当前批次筛选，不能把已被排除的旧帧重新塞回列表。
  if (saved && (!filteredBatchRuns('dataBatch',dataset.runs).some(run=>run.key===saved.run_key) ||
      ($('runSelect').value && $('runSelect').value !== saved.run_key))) {
    showSelectedDataFrame();
    return;
  }
  if (![...$('frameSelect').options].some(option => option.value === singleDataFrame.path))
    $('frameSelect').appendChild(new Option('上次单帧 · ' + frameCaption(singleDataFrame.path), singleDataFrame.path));
  $('frameSelect').value = singleDataFrame.path; $('selectedPath').textContent = singleDataFrame.path;
  renderDisabled();
  displayResult(singleDataFrame); displayedPath = singleDataFrame.path;
  $('framePath').textContent = displayedPath;
  if (singleDataChart && singleDataChart.view === view) {
    chart = singleDataChart; $('chartPlaceholder').classList.add('hidden'); requestAnimationFrame(drawChart);
  } else loadPlot(displayedPath, true);
}

function renderOutputs() {
  const output = state.hardware.outputs || {};
  $('outputBadge').textContent = !output.available ? '未加载硬件' : output.running ? '持续输出中' : '输出已关闭';
  $('outputBadge').classList.toggle('online', !!output.running);
  $('toggleOutputs').textContent = output.enabled ? '关闭持续输出' : '开启持续输出';
  $('toggleOutputs').classList.toggle('danger', !!output.enabled);
  $('toggleOutputs').setAttribute('aria-pressed', String(!!output.enabled));
  if (output.available) {
    const actual = output.actual, ns = value => Number(value.toFixed(3));
    $('outputActual').textContent = `已配置：${Number(actual.frequency_khz.toFixed(6))} kHz；激光相位 ${ns(actual.laser_delay_ns)} ns / 高电平 ${ns(actual.laser_width_ns)} ns；探测开启相位 ${ns(actual.gate_delay_ns)} ns / 低电平时长 ${ns(actual.gate_width_ns)} ns。${output.enabled ? '' : '输出已关闭，接收器保持高电平关闭探测。'}${output.busy ? ' 新参数等待生效。' : ''}${output.error ? ' 上次参数被拒绝。' : ''}`;
    $('referenceActual').textContent = `当前参考：${output.reference_source === 'internal' ? 'DAC1内部回接' : 'B3/A3外部LVDS输入'}；DAC时钟${output.dac_ready ? '已就绪' : '未锁定'}；时间步长8 ns。`;
    if (!outputFieldsLoaded) {
      for (const [id, key] of [['outputFrequency','frequency_khz'], ['laserDelay','laser_delay_ns'], ['laserWidth','laser_width_ns'], ['gateDelay','gate_delay_ns'], ['gateWidth','gate_width_ns']]) $(id).value = Number(actual[key].toFixed(6));
      // API 回读的是原始码；网页显示正向码，刷新页面不会改变实际输出电平。
      for (const [id, key] of [['dac1Low','dac1_low'], ['dac1High','dac1_high'], ['dac2Low','dac2_low'], ['dac2High','dac2_high']]) $(id).value = DacLevels.toPositiveCode(output.levels[key]);
      $('referenceSource').value = output.reference_source;
      outputFieldsLoaded = true;
    }
  }
  OutputTiming.render(output);
  const thresholds = output.thresholds;
  $('thresholdBadge').textContent = !output.available ? '未加载硬件' : thresholds?.busy ? '正在写入' : thresholds?.ready ? '阈值已就绪' : '等待就绪';
  if (thresholds?.available) {
    $('thresholdActual').textContent = `已发送：A ${thresholds.threshold_a_v.toFixed(3)} V；B ${thresholds.threshold_b_v.toFixed(3)} V。${thresholds.error ? ' 上次阈值请求被拒绝，已发送值保持不变。' : ''}`;
    if (thresholds.ready && !thresholdFieldsLoaded) {
      $('thresholdA').value = thresholds.threshold_a_v.toFixed(3);
      $('thresholdB').value = thresholds.threshold_b_v.toFixed(3);
      thresholdFieldsLoaded = true;
    }
  }
}

async function outputAction(body) {
  if (body.action === 'configure') body.timing_schema = 'active_windows_v1';
  const configuring = body.action !== 'enable';
  if (configuring ? outputRequest || outputToggleRequest : outputToggleRequest) return;
  if (configuring) outputRequest = true; else outputToggleRequest = true;
  renderDisabled();
  try {
    const result = await api('/api/outputs', body);
    state.hardware.outputs = result.outputs;
    if (body.action === 'thresholds' || body.action === 'defaults') thresholdFieldsLoaded = false;
    if (body.action === 'defaults') outputFieldsLoaded = false;
    renderOutputs(); toast(body.action === 'defaults' ? '全部参数已恢复默认，持续输出已关闭' : body.action === 'thresholds' ? '两路比较阈值已完成发送' : body.action === 'reference' ? '参考源已切换' : body.action === 'configure' ? '参数已生效，开关状态保持不变' : result.outputs.enabled ? '持续输出已开启' : '持续输出已关闭');
  } catch (error) { toast(error.message, true); }
  finally {
    if (configuring) outputRequest = false; else outputToggleRequest = false;
    renderDisabled(); poll();
  }
}

async function deleteSelectedRun() {
  if (dataDisplayMode !== 'single') return;
  const run = dataset.runs.find(item => item.key === $('runSelect').value);
  if (!run || active() || busyRequest) return;
  if (!await confirmAction({title:'删除采集批次',message:`批次：${run.id}\n将永久删除该批次的全部 ${run.frames} 帧及相关文件。已有模型参数不会自动改变。`,confirmLabel:'永久删除批次'})) return;
  busyRequest = true; renderDisabled();
  try {
    await api('/api/data/delete_run', {collection: run.collection, run_id: run.id});
    if (singleDataFrame && singleDataFrame.path.startsWith(run.key + '/')) singleDataFrame = singleDataChart = null;
    removeDeletedComparison(run.key);
    if ((displayedPath && displayedPath.startsWith(run.key + '/')) ||
        (state.latest && state.latest.path.startsWith(run.key + '/'))) clearFrame();
    await refreshData(); await poll(); toast('所选批次已永久删除');
  } catch (error) { toast(error.message, true); }
  finally { busyRequest = false; renderDisabled(); }
}
async function loadPlot(path, rememberData = false) {
  const requestStarted = performance.now();
  displayedPath = path; const requestedView = view;
  $('framePath').textContent = path.startsWith('memory/') ? '临时帧（未保存）' : path;
  try {
    const result = await api('/api/plot?path=' + encodeURIComponent(path) + '&view=' + requestedView);
    const requestMs = performance.now() - requestStarted;
    if (path !== displayedPath || requestedView !== view) return;
    chart = result; $('chartPlaceholder').classList.add('hidden');
    if (rememberData && singleDataFrame && singleDataFrame.path === path) singleDataChart = result;
    $('chartRange').textContent = result.view === 'full' ? '完整图：线性纵轴 0–500' : '回波区域：线性纵轴自动范围';
    const drawStarted = performance.now(); drawChart();
    $('stagePlotRequest').textContent = formatMilliseconds(requestMs);
    $('stageDraw').textContent = formatMilliseconds(performance.now() - drawStarted);
    return true;
  } catch (error) { toast(error.message, true); }
}
function drawChart() {
  const canvas = $('histogram'); if (!canvas.clientWidth || !chart) return;
  const ratio = window.devicePixelRatio || 1, width = canvas.clientWidth, height = canvas.clientHeight;
  canvas.width = width * ratio; canvas.height = height * ratio;
  const ctx = canvas.getContext('2d'); ctx.scale(ratio, ratio);
  const left = 43, top = 16, right = width - 17, bottom = height - 35;
  const px = value => left + (value - chart.x_min) / Math.max(1, chart.x_max - chart.x_min) * (right - left);
  const py = value => bottom - Math.min(value, chart.y_max) / chart.y_max * (bottom - top);
  ctx.font = '10px Segoe UI, sans-serif'; ctx.lineWidth = 1;
  for (let i = 0; i <= 5; i++) {
    const y = top + (bottom - top) * i / 5;
    ctx.strokeStyle = '#28363e'; ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y); ctx.stroke();
    ctx.fillStyle = '#79909a'; ctx.textAlign = 'right'; ctx.fillText(String(Math.round(chart.y_max * (5 - i) / 5)), left - 9, y + 3);
    const x = left + (right - left) * i / 5;
    ctx.textAlign = 'center'; ctx.fillText(String(Math.round(chart.x_min + (chart.x_max - chart.x_min) * i / 5)), x, bottom + 18);
  }
  ctx.fillStyle = '#8298a2'; ctx.textAlign = 'right'; ctx.fillText('bin 位置', right, height - 3);
  ctx.textAlign = 'left'; ctx.fillText('计数', 3, 10);
  ctx.save(); ctx.beginPath(); ctx.rect(left, top, right - left, bottom - top); ctx.clip();
  ctx.beginPath(); chart.x.forEach((x, index) => { if (!index) ctx.moveTo(px(x), py(chart.y[index])); else ctx.lineTo(px(x), py(chart.y[index])); });
  ctx.strokeStyle = '#58d3cb'; ctx.lineWidth = 1.2; ctx.stroke();
  for (const [bin, color, label, labelRow] of [[chart.reference_bin, '#8da5b8', '参考', 0], [chart.return_bin, '#c6ed87', '回波', 1]]) {
    if (bin === null || bin < chart.x_min || bin > chart.x_max) continue;
    const x = px(bin); ctx.strokeStyle = color; ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(x, top + 18); ctx.lineTo(x, bottom); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = color; ctx.textAlign = x > right - 65 ? 'right' : 'left'; ctx.fillText(label + ' ' + bin, x + (x > right - 65 ? -5 : 5), top + 12 + labelRow * 16);
  }
  ctx.restore();
}
function clearTrainingFigureCache() {
  ++figureRequest;
  if (figureAbort) figureAbort.abort();
  figurePending = null;
  for (const item of figureCache.values()) URL.revokeObjectURL(item.url);
  figureCache.clear(); figureCacheBytes = 0;
}
function showTrainingFigure(url, version, kind) {
  const img = $('trainingFigure');
  // 相同src不重新解码，反复进入页面时也不先清空已有图表。
  if (img.src !== url) img.src = url;
  figureObjectUrl = url;
  img.classList.remove('hidden'); $('figurePlaceholder').classList.add('hidden');
  $('figureStatus').textContent = kind === 'peaks' ? '逐类峰位核验' : '图表已加载';
  $('figureVersion').textContent = '模型版本 ' + version;
  $('trainingFigureCard').classList.remove('is-loading');
}
function waitForChart(signal, milliseconds) {
  return new Promise((resolve, reject) => {
    const aborted = () => { clearTimeout(timer); reject(new DOMException('已取消图表等待', 'AbortError')); };
    const timer = setTimeout(() => { signal.removeEventListener('abort', aborted); resolve(); }, milliseconds);
    if (signal.aborted) aborted(); else signal.addEventListener('abort', aborted, {once:true});
  });
}
async function loadFigure(retry = false) {
  if (retry) clearTrainingFigureCache();
  const img = $('trainingFigure'), version = $('modelSource').value || state?.model.id;
  const kind = figure, query = new URLSearchParams({model_id:version || ''});
  if (kind === 'peaks' && $('trainingPeakClass').value !== '') query.set('class_index', $('trainingPeakClass').value);
  const key = '/api/training/image/' + kind + '?' + query;
  $('peakClassField').classList.toggle('hidden', kind !== 'peaks');
  $('modelFigureHint').classList.toggle('hidden', kind !== 'model');
  if (figurePending?.key === key) return figurePending.promise;
  if (figureCacheVersion !== version) { clearTrainingFigureCache(); figureCacheVersion = version; }
  const id = ++figureRequest;
  if (figureAbort) figureAbort.abort();
  figurePending = null;
  const cached = figureCache.get(key);
  if (cached) {
    figureCache.delete(key); figureCache.set(key, cached);
    showTrainingFigure(cached.url, version, kind); return;
  }
  img.classList.add('hidden'); $('figurePlaceholder').classList.remove('hidden');
  $('figurePlaceholder').textContent = version ? '正在加载所选模型图表…' : '暂无模型版本，请先训练。';
  $('figureStatus').textContent = version ? '正在加载' : '暂无模型';
  $('trainingFigureCard').classList.toggle('is-loading', !!version);
  if (!version) return;
  figureAbort = new AbortController();
  const signal = figureAbort.signal;
  const pending = {key, promise: null, resolve: null};
  pending.promise = new Promise(resolve => { pending.resolve = resolve; });
  figurePending = pending;
  try {
    let response;
    const started = performance.now();
    while (true) {
      response = await fetch(key + (retry ? '&retry=1' : ''), {signal});
      retry = false;
      if (id !== figureRequest) return;
      if (response.status !== 202) break;
      const status = await response.json();
      $('figureStatus').textContent = status.state === 'running' ? '后台绘图中' : '等待绘图';
      $('figurePlaceholder').textContent = (status.message || '正在准备图表') + '；模型可正常使用。';
      if (performance.now() - started > 180000) throw new Error('等待图表超时，可点击重新加载；模型仍可使用');
      await waitForChart(signal, 1000);
    }
    if (!response.ok) {
      const failure = await response.json().catch(() => ({}));
      throw new Error(failure.message || failure.error || '该版本暂无所选评估图表');
    }
    const blob = await response.blob(); if (id !== figureRequest) return;
    const nextUrl = URL.createObjectURL(blob);
    figureCache.set(key, {url:nextUrl, bytes:blob.size}); figureCacheBytes += blob.size;
    while (figureCache.size > 1 && (figureCache.size > 3 || figureCacheBytes > FIGURE_CACHE_BYTES)) {
      const oldest = figureCache.keys().next().value, item = figureCache.get(oldest);
      URL.revokeObjectURL(item.url); figureCache.delete(oldest); figureCacheBytes -= item.bytes;
    }
    showTrainingFigure(nextUrl, version, kind);
  } catch (error) {
    if (error.name === 'AbortError' || id !== figureRequest) return;
    $('figurePlaceholder').textContent = error.message; $('figureStatus').textContent = '图表不可用';
  } finally {
    pending.resolve();
    if (figurePending === pending) figurePending = null;
    if (id === figureRequest) $('trainingFigureCard').classList.remove('is-loading');
  }
}
function renderState() {
  $('connection').textContent = '开发板已连接'; $('connection').className = 'badge online';
  const job = state.job, model = state.model, data = state.dataset;
  const names = {idle: '准备就绪', running: '运行中', stopping: '正在停止', done: '任务完成', error: '任务失败', cancelled: '已停止'};
  $('taskStatus').textContent = names[job.status] || job.status;
  $('taskDescription').textContent = job.message;
  $('datasetFrames').textContent = data.frame_count;
  const trainingMaterials = data.training_materials || data.materials;
  $('datasetDetails').textContent = `${trainingMaterials.length} 种已标注材质 · ${data.specimen_count} 件实物`;
  $('treeCount').textContent = model.available && model.trees ? model.trees + ' 棵树' : model.algorithm === 'mlp' ? (model.feature_count||8)+'→'+(model.hidden_layer_sizes||[32,16]).join('→')+'→C' : model.algorithm === 'tiny_cnn' ? '256点回波 · 4通道卷积' : '';
  $('modelAlgorithmName').textContent = model.available ? model.algorithm_name : '树分类器';
  $('modelDescription').textContent = model.available ? `${model.classes.length} 个类别 · ${model.name}` : '暂无模型，请先训练';
  $('modelId').textContent = model.available ? '模型 ' + model.id : '暂无模型';
  renderModelManager();
  const network = state.network;
  $('networkBadge').textContent = '内部AXI连接';
  $('networkDetails').textContent = '板端地址：' + network.addresses.map(item => `${item.interface} ${item.ip}`).join('；');
  const hardware = state.hardware || {};
  renderOutputs();
  $('inferenceBackend').value = hardware.inference_backend || 'cpu';
  $('compareBackend').value = hardware.inference_backend || 'cpu';
  $('hardwareStatus').textContent = hardware.loaded ? (hardware.faulted ? '接口故障，需重新加载' : (hardware.calibrated ? 'Overlay已加载 · TDC校准完成' : 'Overlay已加载 · 等待TDC校准')) : '尚未加载；CPU演示可直接使用';
  const warn = $('source').value === 'pl' && !hardware.loaded;
  $('notice').classList.toggle('hidden', !warn);
  $('notice').textContent = '内部采集需要先加载本项目Overlay。网页文件和训练功能可以先运行。';
  const progress = job.target > 0 ? Math.min(100, job.completed / job.target * 100) : (active() ? 25 : 100);
  $('progressBar').style.width = job.status === 'idle' ? '0%' : progress + '%';
  $('progressTrack').classList.toggle('is-error', job.status === 'error');
  $('progressTrack').classList.toggle('is-running', active());
  $('progressText').textContent = job.kind === 'train' ? (active() ? '训练中，请查看日志' : job.status === 'done' && Number.isFinite(job.model_ready_seconds) ? `模型已可用，用时 ${job.model_ready_seconds.toFixed(3)} 秒；图表按需生成` : job.message) : job.completed ? `已完成 ${job.completed}${job.target ? ' / ' + job.target : ''} 帧` : job.message;
  const logs = $('logs'), wasBottom = logs.scrollTop + logs.clientHeight >= logs.scrollHeight - 35;
  const newestLog = state.logs.length ? String(state.logs[state.logs.length - 1].id) : '';
  if (newestLog !== logSignature) {
    logSignature = newestLog; logs.replaceChildren();
    for (const item of state.logs.slice(-70)) {
      const row = document.createElement('div'); row.className = 'log-line';
      const time = document.createElement('time'); time.textContent = item.time;
      const text = document.createElement('span'); text.textContent = item.message; row.append(time, text); logs.appendChild(row);
    }
    if (wasBottom) logs.scrollTop = logs.scrollHeight;
  }
  if (state.latest) {
    // 按发布标识刷新：同一帧重复推理，即使类别和分数不变，也应展示新结果。
    const signature = state.latest.result_id || JSON.stringify(state.latest);
    if (signature !== latestSignature) {
      latestSignature = signature;
      if (state.latest.source === 'file') {
        singleDataFrame = state.latest; singleDataChart = null;
        if (panel === 'data' && dataDisplayMode === 'single') { displayResult(state.latest); loadPlot(state.latest.path, true); }
      }
      // 参数页和模型页不显示直方图，不能在后台持续为它们读取整帧、计算取图。
      if (panel !== 'data') displayResult(state.latest);
      if (panel === 'capture') {
        const frame = state.latest;
        loadPlot(frame.path).then(drawn => { if (drawn && frame.source === 'history') return api('/api/demo/ack', {result_id:frame.result_id}); }).catch(error => toast(error.message,true));
      } else if (state.latest.source === 'history') {
        api('/api/demo/ack', {result_id:state.latest.result_id}).catch(() => {});
      }
    }
  }
  const completedTraining = job.kind === 'train' && job.status === 'done' ? job.id : '';
  if (completedTraining && completedTraining !== trainingSignature) {
    trainingSignature = completedTraining;
    refreshModels(job.trained_model_id).then(() => { if (panel === 'train') loadFigure(); }).catch(error => toast(error.message, true));
    refreshData().catch(() => {});
  }
  // 波形和识别结果逐帧更新；采集进度本身不触发全量批次列表重建。
  if (shouldRefreshDataset(data)) refreshData().catch(() => {});
  updateComparisonState();
  renderCaptureHistory(state.capture_history);
  renderDisabled();
}
async function poll() {
  if (pollRequest) return pollRequest;
  pollRequest = (async () => {
    try {
      const query = new URLSearchParams({after_frame: captureCursor, capture_job: captureJobId});
      state = await api('/api/state?' + query); renderState();
    } catch (_) { $('connection').textContent = '连接中断'; $('connection').className = 'badge amber'; }
  })();
  try { await pollRequest; } finally { pollRequest = null; }
}
function schedulePoll(delay) { clearTimeout(cycleTimer); cycleTimer = setTimeout(cycle, delay); }
async function cycle() { await poll(); schedulePoll(active() ? 200 : 1500); }

document.querySelectorAll('.nav').forEach(button => button.addEventListener('click', () => switchPanel(button.dataset.panel)));
$('source').addEventListener('change', () => { updateSource(); if (state) renderState(); });
$('saveData').addEventListener('change', updateSource);
$('singleCapture').addEventListener('click', event => action('/api/jobs/capture', captureOptions(1, false),{button:event.currentTarget,pending:'正在启动…'}));
$('batchCapture').addEventListener('click', event => action('/api/jobs/capture', captureOptions(Number($('frameCount').value), false),{button:event.currentTarget,pending:'正在启动…'}));
$('continuousCapture').addEventListener('click', event => action('/api/jobs/capture', captureOptions(Number($('frameCount').value), true),{button:event.currentTarget,pending:'正在启动…'}));
document.querySelectorAll('.stop-button').forEach(button => button.addEventListener('click', () => action('/api/jobs/stop', {})));
$('refreshData').addEventListener('click', () => refreshData().then(() => toast('数据列表已刷新')).catch(error => toast(error.message, true)));
$('runSelect').addEventListener('change', () => { fillFrames(); if (dataDisplayMode === 'single') showSelectedDataFrame(); });
$('deleteRun').addEventListener('click', deleteSelectedRun);
$('applyOutputs').addEventListener('click', () => {
  try {
    // 只在提交时还原为 DAC 原始码，驱动和硬件接口保持原有约定。
    const levels = {};
    for (const [id, key] of [['dac1Low','dac1_low'], ['dac1High','dac1_high'], ['dac2Low','dac2_low'], ['dac2High','dac2_high']])
      levels[key] = DacLevels.toRawCode($(id).value);
    outputAction({action: 'configure', frequency_khz: $('outputFrequency').value,
      laser_delay_ns: $('laserDelay').value, laser_width_ns: $('laserWidth').value,
      gate_delay_ns: $('gateDelay').value, gate_width_ns: $('gateWidth').value, ...levels});
  } catch (error) { toast(error.message, true); }
});
$('applyReference').addEventListener('click', () => outputAction({action: 'reference', source: $('referenceSource').value}));
$('applyThresholds').addEventListener('click', () => outputAction({action: 'thresholds', threshold_a_v: $('thresholdA').value, threshold_b_v: $('thresholdB').value}));
$('restoreDefaults').addEventListener('click', () => outputAction({action: 'defaults'}));
$('toggleOutputs').addEventListener('click', () => outputAction({action: 'enable', enabled: !state.hardware.outputs.enabled}));
$('recognizeFile').addEventListener('click', () => {
  if (active() || busyRequest) return;
  const path = $('frameSelect').value; if (!path) return toast('请选择或上传一帧 CSV', true);
  showSingleDataFrame(path);
  action('/api/jobs/recognize', {path});
});
$('plotFile').addEventListener('click', () => { const path = $('frameSelect').value; if (path) showSingleDataFrame(path); });
$('frameSelect').addEventListener('change', () => { $('selectedPath').textContent = $('frameSelect').value; if (dataDisplayMode === 'single' && $('frameSelect').value) showSingleDataFrame($('frameSelect').value); });
$('upload').addEventListener('change', async event => {
  const file = event.target.files[0]; if (!file) return;
  const data = new FormData(); data.append('file', file);
  try {
    const result = await api('/api/upload', data, true); selectedUpload = {path: result.path, name: file.name};
    fillFrames(); $('frameSelect').value = result.path; $('selectedPath').textContent = file.name;
    renderDisabled();
    if (dataDisplayMode === 'single') { toast('上传完成，可查看或识别这一帧'); showSingleDataFrame(result.path); }
    else toast('上传完成，点击“加入所选帧”添加到对比列表');
  } catch (error) { toast(error.message, true); }
  event.target.value = '';
});
$('startTrain').addEventListener('click', event => action('/api/jobs/train', {
  trees: Number($('trees').value), max_depth: Number($('depth').value),
  algorithm: $('trainingAlgorithm').value, name: $('modelName').value.trim(),
  tune: $('tuneModel').checked, activate: $('activateTrainedModel').checked, run_keys: [...(trainingRunSelection || [])]
},{button:event.currentTarget,pending:'正在提交训练…'}));
document.querySelectorAll('.view-button').forEach(button => button.addEventListener('click', () => {
  view = button.dataset.view; document.querySelectorAll('.view-button').forEach(item => { item.classList.toggle('active', item === button);item.setAttribute('aria-pressed',String(item===button)); });
  if (displayedPath) loadPlot(displayedPath, panel === 'data');
}));
document.querySelectorAll('.figure-button').forEach(button => button.addEventListener('click', () => {
  figure = button.dataset.figure; document.querySelectorAll('.figure-button').forEach(item => { item.classList.toggle('active', item === button);item.setAttribute('aria-pressed',String(item===button)); }); loadFigure();
}));
$('trainingPeakClass').addEventListener('change', loadFigure);
$('trainingFigure').addEventListener('error', () => { clearTrainingFigureCache(); $('trainingFigure').classList.add('hidden'); $('figurePlaceholder').classList.remove('hidden'); $('figurePlaceholder').textContent='图表无法显示，请重新选择模型或刷新图表。';$('figureStatus').textContent='图表不可用'; });
$('refreshTrainingFigure').addEventListener('click', () => loadFigure(true));
window.addEventListener('resize', drawChart);
initializeRangeCalibration(); initializeUiControls(); initializeComparison(); initializeBatchPickers(); initializeModelManager(); updateSource(); refreshData().catch(error => toast(error.message, true)); cycle();
['loadOverlay', 'loadOutputOverlay'].forEach(id => $(id).addEventListener('click', () => action('/api/hardware', {action: 'load'})));
$('inferenceBackend').addEventListener('change', () => action('/api/hardware', {action: $('inferenceBackend').value}));
