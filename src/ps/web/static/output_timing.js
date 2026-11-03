/* 使用硬件回读的窗口区间绘制时序；不把示意图当作示波器实测。 */
(function () {
  'use strict';
  function describe(output) {
    if (!output.available || output.timing_schema !== 'active_windows_v1' || !output.windows) return null;
    const windows = output.windows, period = windows.period_ns;
    if (!Number.isFinite(period) || period <= 0) throw new Error('时序周期无效');
    const rows = {};
    for (const key of ['laser','gate']) {
      rows[key] = windows[key].segments_ns.map(([start,end]) => {
        if (![start,end].every(Number.isFinite) || start < 0 || end <= start || end > period)
          throw new Error('时序窗口无效');
        return {start,end,left:100*start/period,width:100*(end-start)/period};
      });
    }
    return {period,rows,enabled:!!output.enabled,wraps:!!windows.gate.wraps_cycle};
  }
  function render(output) {
    const $ = id => document.getElementById(id), data = describe(output);
    for (const id of ['laserTimingTrack','gateTimingTrack']) $(id).replaceChildren();
    $('outputTiming').classList.toggle('timing-off', !data?.enabled);
    $('timingState').textContent = !data ? '加载版本5 Overlay后显示' : data.enabled ? '持续输出中' : '输出关闭 · 以下仅显示已配置区间';
    $('timingPeriod').textContent = data ? data.period + ' ns' : '—';
    if (!data) {
      $('timingRanges').textContent = '相位相对周期起点；绿色表示低电平探测窗口。';
      return;
    }
    for (const [key,id] of [['laser','laserTimingTrack'],['gate','gateTimingTrack']]) {
      for (const segment of data.rows[key]) {
        const bar = document.createElement('span');bar.className='timing-segment';
        bar.style.left=segment.left+'%';bar.style.width=segment.width+'%';
        bar.title=`${segment.start}–${segment.end} ns`;
        $(id).appendChild(bar);
      }
    }
    const ranges = data.rows.gate.map(s=>`[${s.start}, ${s.end}) ns`).join('、');
    $('timingRanges').textContent = `每周期允许探测：${ranges}${data.wraps ? '（跨周期）' : ''}。下降沿开启、上升沿关闭；图中不含器件和线缆延迟。`;
  }
  const api = Object.freeze({describe,render});
  if (typeof module !== 'undefined' && module.exports) module.exports=api;
  if (typeof window !== 'undefined') window.OutputTiming=api;
})();
