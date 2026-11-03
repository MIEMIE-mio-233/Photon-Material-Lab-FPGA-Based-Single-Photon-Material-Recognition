/* 离线检查真实前端批次选择/版本浏览/切换事件，不发送任何硬件命令。 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor() { this.value = ''; this.children = []; this.events = {}; this.disabled = false; this.classList={toggle:()=>{}}; }
  contains(node) { return node===this || this.children.includes(node); }
  replaceChildren(...nodes) { this.children = nodes; this.value = nodes[0]?.value || ''; }
  appendChild(node) { this.children.push(node); if (!this.value && node.value) this.value = node.value; return node; }
  append(...nodes) { this.children.push(...nodes); }
  addEventListener(name, handler) { this.events[name] = handler; }
}

(async () => {
  const elements = new Map(), calls = [];
  const get = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  const version = (id, name) => ({id, name, algorithm_name:name, trees:32, nodes:100, classes:['a','b'], samples:30,
    accuracy:0.9, training_runs:['dataset/run_a','dataset/run_b'], pl_compatible:true, pl_parameter_bytes:4800, created_at:'2026-10-19'});
  const catalog = [version('rf','随机森林'), Object.assign(version('cnn','小型CNN'),{algorithm:'tiny_cnn'})];
  const context = {
    state:{model:catalog[0], model_memory:{}}, panel:'train',
    dataset:{runs:[{key:'dataset/run_a',id:'run_a',material:'a',materials:['a'],specimen:'a1',labeled_frames:10},
      {key:'dataset/run_b',id:'run_b',material:'b',materials:['b'],specimen:'b1',labeled_frames:20},
      {key:'dataset/run_u',id:'run_u',material:'unlabeled',labeled_frames:0}]},
    illuminationName:()=>"光照未标注", $:get, Option:function(text,value){this.text=text;this.value=value;},
    document:{createElement:()=>new Element(), addEventListener:()=>{}, querySelectorAll:()=>get('trainingRuns').children.flatMap(row=>row.children.filter(child=>child.type==='checkbox'))},
    confirmAction:async()=>true,
    renderDisabled:()=>vm.runInContext('renderModelControls(false)',context), toast:message=>{throw new Error(message);}, loadFigure:()=>{},
    api:async route=>{assert.equal(route,'/api/models');return {models:catalog,active_model_id:context.state.model.id};},
    action:async (route,body)=>{calls.push({route,body});if(route==='/api/models/delete')catalog.splice(catalog.findIndex(item=>item.id===body.model_id),1);else context.state.model=catalog.find(item=>item.id===body.model_id);}
  };
  vm.createContext(context);
  for(const name of ['batch_picker.js','model_manager.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/static/'+name),'utf8'),context);
  get('trees').value=32; get('trainingAlgorithm').value='random_forest';
  vm.runInContext('initializeModelManager(); renderTrainingRuns();',context);
  await vm.runInContext('refreshModels()',context);
  assert.equal(get('trainingRuns').children.length,2);
  assert.match(get('trainingSelectionSummary').textContent,/2 批次 \/ 30 帧/);
  get('clearTrainingRuns').events.click();
  assert.equal(get('startTrain').disabled,true);
  get('selectAllTrainingRuns').events.click();
  assert.equal(get('startTrain').disabled,false);
  const checkbox=get('trainingRuns').children[0].children[0]; checkbox.checked=false; checkbox.events.change();
  assert.match(get('trainingSelectionSummary').textContent,/1 批次 \/ 10 帧/); // 最新批次run_b排在首位。
  get('modelSource').value='cnn'; get('modelSource').events.change();
  assert.equal(calls.length,0); assert.equal(context.state.model.id,'rf');
  await get('applyModelVersion').events.click();
  assert.equal(context.state.model.id,'cnn'); assert.equal(calls.length,1);
  assert.equal(get('deleteModelVersion').disabled,true);
  get('modelSource').value='rf';get('modelSource').events.change();
  assert.equal(get('deleteModelVersion').disabled,false);
  await get('deleteModelVersion').events.click();
  assert.equal(catalog.length,1);assert.equal(calls[1].route,'/api/models/delete');
  assert.equal(context.state.model.id,'cnn');
  get('trainingAlgorithm').value='decision_tree'; get('trainingAlgorithm').events.change();
  assert.equal(get('trees').value,1); assert.equal(get('trees').disabled,true);
  get('trainingAlgorithm').value='random_forest'; get('trainingAlgorithm').events.change();
  assert.equal(get('trees').value,32); assert.equal(get('trees').disabled,false);
  get('trainingAlgorithm').value='tiny_cnn';get('trainingAlgorithm').events.change();
  assert.equal(get('trees').disabled,true);assert.equal(get('depth').disabled,true);
  vm.runInContext('renderModelControls(true)',context);
  assert.equal(get('applyModelVersion').disabled,true); assert.equal(get('startTrain').disabled,true);
  // 旧网页即使提交已下线算法，也不能启用训练。
  get('selectAllTrainingRuns').events.click();
  get('trainingAlgorithm').value='unsupported_model';get('trainingAlgorithm').events.change();
  assert.equal(get('startTrain').disabled,true);
  get('trainingAlgorithm').value='random_forest';get('trainingAlgorithm').events.change();
  assert.equal(get('startTrain').disabled,false);
  console.log('PASS: batch filtering/counts, empty selection, browse without switch, explicit switch, single-tree controls and busy lock.');
})().catch(error=>{console.error(error);process.exit(1);});
