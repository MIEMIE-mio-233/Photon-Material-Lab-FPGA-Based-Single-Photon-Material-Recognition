'use strict';
function renderRangeControls(isBusy=false){
 const data=state?.range_calibration||{},profile=data.profile,points=data.points||[];
 $('rangeKnownDistance').disabled=isBusy;
 $('captureRangePoint').disabled=isBusy||!state?.hardware?.loaded;
 $('captureRangePoint').textContent=isBusy&&state?.job?.kind==='range_point'?`采集中 ${state.job.completed}/10`:'采集此点（10帧）';
 const configMatches=points.every(p=>p.signature===data.current_signature);
 $('applyRangeMulti').disabled=isBusy||!configMatches||new Set(points.map(p=>p.distance_cm)).size<3||points.some(p=>p.frame_count!==10);
 $('rangeCalibrationStatus').textContent=profile?`${profile.timing_signature===data.current_signature?'校准已应用':'配置已变化，请重新校准'} · ${profile.points.length}点 · 拟合残差 ${profile.fit_mae_cm.toFixed(3)} cm`:`待应用 · 已采集 ${points.length} 个点`;
 $('rangePoints').replaceChildren();
 if(!points.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=6;td.textContent='尚未采集校准点';td.className='muted';tr.append(td);$('rangePoints').append(tr);}
 points.forEach((p,i)=>{const tr=document.createElement('tr');for(const v of[i+1,p.distance_cm.toFixed(2),p.frame_count||1,p.reference_bin,p.return_bin]){const td=document.createElement('td');td.textContent=v;tr.append(td);}const td=document.createElement('td'),btn=document.createElement('button');btn.className='button danger small';btn.textContent='删除';btn.disabled=isBusy;btn.setAttribute('aria-label',`删除${p.distance_cm} cm校准点`);btn.addEventListener('click',()=>action('/api/range-calibration',{action:'delete_point',point_id:p.id},{button:btn,pending:'删除中…'}));td.append(btn);tr.append(td);$('rangePoints').append(tr);});
}
function initializeRangeCalibration(){
 $('captureRangePoint').addEventListener('click',e=>action('/api/jobs/range_point',{distance_cm:$('rangeKnownDistance').value},{button:e.currentTarget,pending:'正在采集…'}));
 $('applyRangeMulti').addEventListener('click',e=>action('/api/range-calibration',{action:'apply_multi'},{button:e.currentTarget,pending:'拟合中…'}));
}
