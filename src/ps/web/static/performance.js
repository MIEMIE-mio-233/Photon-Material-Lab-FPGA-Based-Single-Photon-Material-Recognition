/* 分段计时和逐帧结果：曲线显示最新帧，表格增量保留本任务最近128帧。 */
'use strict';
let captureCursor = 0, captureJobId = '', captureRows = [];
function renderFrameStages(frame) {
  const t = frame.timing;
  $('frameStages').classList.toggle('hidden', !t);
  if (!t) return;
  for (const [id, value] of [['stageAcquire', t.acquire_ms], ['stageRead', (t.read_ms || 0) + (t.file_read_ms || 0)],
      ['stageSave', t.save_ms], ['stageFrame', t.frame_total_ms], ['stageInterval', t.interval_ms]])
    $(id).textContent = formatMilliseconds(value);
  $('stagePlotRequest').textContent = '—'; $('stageDraw').textContent = '—';
}
function renderCaptureHistory(history) {
  if (!history) return;
  if ((history.job_id || '') === captureJobId && !history.frames.length) { captureCursor = history.cursor; return; }
  if (history.job_id !== captureJobId) { captureJobId = history.job_id || ''; captureRows = []; }
  for (const row of history.frames) {
    if (!captureRows.some(saved => saved.id === row.id)) captureRows.push(row);
  }
  captureRows = captureRows.slice(-128);
  captureCursor = history.cursor;
  $('captureHistoryInfo').textContent = `本任务已完成 ${history.total} 帧 · 列表保留最近128帧`;
  $('captureRows').replaceChildren();
  if (!captureRows.length) {
    const row = document.createElement('tr'), cell = document.createElement('td');
    cell.colSpan = 9; cell.className = 'muted'; cell.textContent = '开始采集后逐帧记录结果和耗时';
    row.appendChild(cell); $('captureRows').appendChild(row); return;
  }
  for (const item of [...captureRows].reverse()) {
    const row = document.createElement('tr'), t = item.timing;
    const values = [item.frame_index, item.error || item.material || '未识别', item.saved ? '已保存' : item.source === 'history' ? '历史帧' : '未保存',
      formatMilliseconds(t.frame_total_ms), formatMilliseconds(t.acquire_ms), formatMilliseconds((t.read_ms || 0) + (t.file_read_ms || 0)),
      formatMilliseconds(t.save_ms), formatMilliseconds(t.inference_ms), formatMilliseconds(t.interval_ms)];
    for (const value of values) { const cell = document.createElement('td'); cell.textContent = value; row.appendChild(cell); }
    $('captureRows').appendChild(row);
  }
}
