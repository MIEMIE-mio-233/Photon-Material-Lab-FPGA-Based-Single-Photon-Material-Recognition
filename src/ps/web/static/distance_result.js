/* 现场校准仅用于显示估计距离，不选择分类子模型。 */
'use strict';
function renderDistanceResult(result) {
  $('distanceResult').textContent = Number.isFinite(result?.estimated_distance_cm)
    ? `估计距离 ${result.estimated_distance_cm.toFixed(2)} cm${result.range_correction_applied?' · 现场校准':' · 校准估距'}`
    : result?.distance_warning || '';
  $('distanceResult').classList.toggle('hidden', !$('distanceResult').textContent);
}
