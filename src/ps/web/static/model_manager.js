/* 模型版本只索引元数据，批次选择只传编号；不在浏览器或板端复制数据集。 */
'use strict';
let modelCatalog = [], trainingRunSelection = null, modelCatalogRequest = null;
let previousForestTrees = 32, knownActiveModelId = null;
let previousTrainingAlgorithm = 'random_forest', peakModelId = null;
let capturePickerActiveId = null;

function trainableRuns() { return dataset.runs.filter(run => (run.labeled_frames ?? (run.material === 'unlabeled' ? 0 : run.frames)) > 0); }

function renderTrainingSelection() {
  const selected = trainableRuns().filter(run => trainingRunSelection?.has(run.key));
  const frames = selected.reduce((total, run) => total + (run.labeled_frames ?? run.frames), 0);
  const classes = [...new Set(selected.flatMap(run => run.materials || [run.material]))].sort();
  $('trainingSelectionSummary').textContent = `已选 ${selected.length} 批次 / ${frames} 帧`;
  $('trainingClasses').textContent = `${classes.length} 类 / ${frames} 帧`;
  $('trainingClassNames').textContent = classes.join(' · ') || '请选择有材质标签的批次';
}

function renderTrainingRuns() {
  const runs = trainableRuns(), keys = new Set(runs.map(run => run.key));
  if (trainingRunSelection === null) trainingRunSelection = new Set(keys);
  else trainingRunSelection = new Set([...trainingRunSelection].filter(key => keys.has(key)));
  $('trainingRuns').replaceChildren();
  const visibleRuns=filteredBatchRuns('trainBatch',runs);
  for (const run of visibleRuns) {
    const row = document.createElement('label'); row.className = 'training-run';
    const box = document.createElement('input'); box.type = 'checkbox'; box.value = run.key;
    box.checked = trainingRunSelection.has(run.key);
    const title = document.createElement('span'); title.textContent = `${(run.materials || [run.material]).join(' / ')} · ${run.specimen} · ${run.distance_cm ?? "未知"} cm · ${illuminationName(run.illumination)} · ${run.labeled_frames ?? run.frames} 帧`;
    const detail = document.createElement('small'); detail.textContent = `${batchDate(run)} · ${run.id}`;
    box.addEventListener('change', () => {
      if (box.checked) trainingRunSelection.add(run.key); else trainingRunSelection.delete(run.key);
      renderTrainingSelection(); renderDisabled();
    });
    row.append(box, title, detail); $('trainingRuns').appendChild(row);
  }
  if (!visibleRuns.length) $('trainingRuns').textContent = runs.length ? '没有匹配的批次' : '暂无可训练的已标注批次。';
  renderTrainingSelection();
}

function renderModelVersion() {
  const version = modelCatalog.find(item => item.id === $('modelSource').value);
  if (!version) { $('modelVersionDetails').textContent = '还没有模型版本，请先训练。'; return; }
  const accuracy = Number.isFinite(version.accuracy) ? (version.accuracy * 100).toFixed(1) + '%' : '未评估';
  const activeLabel = state?.model.id === version.id ? '当前识别模型' : '未启用';
  const structure = version.algorithm === 'mlp' ? `${version.feature_count||8}→${(version.hidden_layer_sizes||[32,16]).join("→")}→${version.classes.length}` : version.algorithm === 'tiny_cnn' ? `256点→Conv4×5→平均池化＋9维→8→${version.classes.length}` : `${version.trees} 棵树 / ${version.nodes} 节点`;
  const specific = {

    random_forest:['森林集成表现','新版本展示既有留出集上的单树与累计集成准确率，以及最终森林的叶节点规模；历史版本仅展示结构统计。'],
    decision_tree:['决策分支结构','展示最终部署决策树的前3层；更深分支折叠，节点中的主类与样本数来自已训练模型。'],
    tiny_cnn:['CNN损失与卷积核','展示训练损失与4个可学习卷积核；识别效果以独立留出数据为准。'],
    mlp:['MLP结构与权重','展示实际网络层数和输出层连接权重；当前LBFGS优化器不提供逐轮损失曲线。']
  }[version.algorithm] || ['模型结构分析','展示所选历史模型的结构信息。'];
  $('modelFigureButton').textContent = specific[0];
  $('modelFigureHint').textContent = specific[1];
  const timingLabel = version.feature_count===9 ? (version.timing_reference_source==='training_fe_15cm' ? `Fe时移基线 ${version.timing_reference_bin.toFixed(2)} bin` : '绝对峰位（无15cm Fe参考）') : '历史8维特征';
  $('modelVersionDetails').textContent = `${version.name} · ${activeLabel} · ${timingLabel}${version.retired ? ' · 该算法已停用，仅可浏览或删除' : ''}`;
  for (const [id,value] of [['versionStructure',`${version.algorithm_name} · ${structure}`],
    ['versionSamples',`${version.classes.length} 类 / ${version.samples} 帧`],['versionAccuracy',accuracy],
    ['versionCapacity',`${version.retired ? '该算法已停用' : version.pl_compatible ? '支持PL推理' : '仅支持PS推理'} · ${(version.pl_parameter_bytes/1024).toFixed(1)} KiB`],
    ['versionRuns',version.training_runs.length ? `${version.training_runs.length} 个批次` : '历史版本未记录'],
    ['versionCreated',new Date(version.created_at).toLocaleString('zh-CN',{hour12:false})]]) $(id).textContent=value;
  $('validationHint').textContent = (version.holdout_method || '').includes('diagnostic only') ? '验证范围：同一实物的帧内留出，仅用于诊断，不代表新实物识别准确率。' : '验证结果对应所选模型的留出数据；请结合独立实物测试评估泛化能力。';
  for (const [id,kind] of [['downloadSelectedNative','native'],['downloadSelectedPortable','portable'],['downloadSelectedReport','report']])
    $(id).href='/api/model/download/'+kind+'?model_id='+encodeURIComponent(version.id);
  if (peakModelId !== version.id) {
    peakModelId=version.id; $('trainingPeakClass').replaceChildren();
    version.classes.forEach((name,index)=>$('trainingPeakClass').appendChild(new Option(name,String(index))));
  }
}

async function refreshModels(preferredId) {
  if (modelCatalogRequest) return modelCatalogRequest;
  modelCatalogRequest = (async () => {
    const response = await api('/api/models');
    const previous = preferredId || $('modelSource').value || response.active_model_id;
    modelCatalog = response.models;
    $('modelSource').replaceChildren();
    for (const version of modelCatalog) {
      const mark = version.retired ? '已停用 · ' : version.id === response.active_model_id ? '使用中 · ' : '';
      $('modelSource').appendChild(new Option(`${mark}${version.name} · ${version.algorithm_name} · ${version.id}`, version.id));
    }
    if (!modelCatalog.length) $('modelSource').appendChild(new Option('暂无模型', ''));
    else $('modelSource').value = modelCatalog.some(item => item.id === previous) ? previous : response.active_model_id || modelCatalog[0].id;
    const capturePrevious=$('captureModelSelect').value;
    $('captureModelSelect').replaceChildren();
    modelCatalog.filter(version=>!version.retired).forEach(version=>
      $('captureModelSelect').appendChild(new Option(`${version.id===response.active_model_id?'使用中 · ':''}${version.name} · ${version.algorithm_name}`,version.id)));
    $('captureModelSelect').value=capturePickerActiveId===response.active_model_id && modelCatalog.some(item=>item.id===capturePrevious&&!item.retired) ? capturePrevious : response.active_model_id || '';
    capturePickerActiveId=response.active_model_id;
    renderModelVersion(); renderDisabled();
  })();
  try { await modelCatalogRequest; } finally { modelCatalogRequest = null; }
}

function renderModelManager() {
  renderModelVersion();
  const memory = state.model_memory || {};
  const resident = memory.ps_model_loaded ? 'PS模型已加载' : memory.pl_model_loaded ? `PL模型已加载，参数 ${(memory.pl_parameter_bytes / 1024).toFixed(1)} KiB` : '当前未加载模型参数';
  $('modelMemory').textContent = `${resident}${memory.loaded_model_id ? ' · ' + memory.loaded_model_id : ''}；未选版本仅保存在SD卡，切换后按需加载。`;
  if (knownActiveModelId !== state.model.id) {
    knownActiveModelId = state.model.id;
    refreshModels().catch(error => toast(error.message, true));
  }
}

function renderModelControls(isBusy) {
  for (const id of ['applyModelVersion', 'refreshModels', 'trainingAlgorithm', 'modelName', 'depth', 'activateTrainedModel', 'selectAllTrainingRuns', 'selectOnlyFilteredRuns','clearTrainingRuns','captureModelSelect']) $(id).disabled = isBusy;
  const captureVersion=modelCatalog.find(item=>item.id===$('captureModelSelect').value);
  $('applyCaptureModel').disabled=isBusy || !captureVersion || captureVersion.retired || captureVersion.id===state?.model.id;
  const chosen = modelCatalog.find(item => item.id === $('modelSource').value);
  $('applyModelVersion').disabled = isBusy || !chosen || chosen.retired || chosen.id === state?.model.id;
  $('deleteModelVersion').disabled = isBusy || !chosen || chosen.id === state?.model.id;
  $('deleteModelVersion').title = chosen?.id === state?.model.id ? '先切换其他识别模型，再删除当前版本' : '永久删除所选模型的参数和图表，保留数据集';
  const algorithm = $('trainingAlgorithm').value, dense = ['tiny_cnn', 'mlp'].includes(algorithm);
  $('trees').disabled = isBusy || algorithm!=='random_forest';
  $('depth').disabled = isBusy || dense;
  $('treeCountField').classList.toggle('hidden', dense);
  $('treeDepthField').classList.toggle('hidden', dense);
  $('tuneModelField').classList.toggle('hidden',algorithm!=='mlp'); $('tuneModel').disabled=isBusy || algorithm!=='mlp';
  $('algorithmHint').textContent = algorithm === 'mlp' ? '两层小型网络；勾选调参可比较8/4、16/8、32/16及正则强度，补零复用既有PL核。' : algorithm === 'tiny_cnn' ? '256点归一化回波与9维统计联合输入；4个5点卷积核，8点平均池化，8神经元隐藏层。支持PS/PL，卷积与全连接复用乘加器。' : '树模型复用通用节点核；决策树固定1棵，随机森林可调整树数和深度。';
  document.querySelectorAll('#trainingRuns input').forEach(box => { box.disabled = isBusy; });
  const counts = new Map();
  if (Array.isArray(dataset.frames)) {
    dataset.frames.filter(frame => trainingRunSelection?.has(frame.run_key) && frame.material !== 'unlabeled' && frame.material !== 'bgm' && (frame.sample_kind||'material')==='material').forEach(frame => counts.set(frame.material,(counts.get(frame.material)||0)+1));
  } else trainableRuns().filter(run=>trainingRunSelection?.has(run.key)).forEach(run=>counts.set(run.material,(counts.get(run.material)||0)+(run.labeled_frames ?? run.frames)));
  const supported = ['random_forest','decision_tree','mlp','tiny_cnn'].includes(algorithm);
  const valid = supported && counts.size >= 2 && [...counts.values()].every(value=>value>=2);
  $('startTrain').disabled = isBusy || !valid;
  $('startTrain').title = valid ? '使用所选批次训练并保存独立模型版本' : !supported ? '该训练算法已停用，请刷新网页' : '至少选择两种材质，每种材质不少于2帧';
}

function initializeModelManager() {
  $('trainingAlgorithm').addEventListener('change', () => {
    if (previousTrainingAlgorithm==='random_forest') previousForestTrees = Number($('trees').value);
    previousTrainingAlgorithm = $('trainingAlgorithm').value;
    $('trees').value = previousTrainingAlgorithm === 'decision_tree' ? 1 : previousForestTrees;
    renderDisabled();
  });
  $('selectAllTrainingRuns').addEventListener('click', () => {
    if(trainingRunSelection===null)trainingRunSelection=new Set();
    filteredBatchRuns('trainBatch',trainableRuns()).forEach(run=>trainingRunSelection.add(run.key));renderTrainingRuns();renderDisabled();
  });
  $('selectOnlyFilteredRuns').addEventListener('click',()=>{
    trainingRunSelection=new Set(filteredBatchRuns('trainBatch',trainableRuns()).map(run=>run.key));renderTrainingRuns();renderDisabled();
  });
  $('clearTrainingRuns').addEventListener('click', () => {
    trainingRunSelection = new Set(); renderTrainingRuns(); renderDisabled();
  });
  $('modelSource').addEventListener('change', () => { renderModelVersion(); renderDisabled(); if (panel === 'train') loadFigure(); });
  $('captureModelSelect').addEventListener('change',renderDisabled);
  $('applyCaptureModel').addEventListener('click',async()=>{
    const selected=$('captureModelSelect').value;
    const success=await action('/api/model',{model_id:selected},{button:$('applyCaptureModel'),pending:'正在启用…',success:'识别模型已切换'});
    if(success!==false)await refreshModels(selected);
  });
  $('refreshModels').addEventListener('click', () => {
    // 用户主动刷新时重新取图，避免同一版本的评估图片在外部更新后仍显示旧内容。
    clearTrainingFigureCache();
    refreshModels().then(() => { if (panel === 'train') loadFigure(); }).catch(error => toast(error.message, true));
  });
  $('applyModelVersion').addEventListener('click', async () => {
    const selected = $('modelSource').value;
    const success=await action('/api/model', {model_id: selected}, {button:$('applyModelVersion'),pending:'正在启用…',success:'所选模型已启用'});
    if (success === false) return;
    await refreshModels(selected); if (panel === 'train') loadFigure();
  });
  $('deleteModelVersion').addEventListener('click', async () => {
    const chosen = modelCatalog.find(item => item.id === $('modelSource').value);
    if (!chosen || chosen.id === state?.model.id) return;
    if (!await confirmAction({title:'删除模型版本',message:`模型：${chosen.name}\n版本：${chosen.id}\n将永久删除参数与评估图表，原始采集数据保留。`,confirmLabel:'永久删除版本'})) return;
    const success=await action('/api/models/delete', {model_id: chosen.id}, {button:$('deleteModelVersion'),pending:'正在删除…',success:'模型版本已删除'});
    if (success === false) return;
    await refreshModels(state?.model.id); if (panel === 'train') loadFigure();
  });
  refreshModels().catch(error => toast(error.message, true));
}
