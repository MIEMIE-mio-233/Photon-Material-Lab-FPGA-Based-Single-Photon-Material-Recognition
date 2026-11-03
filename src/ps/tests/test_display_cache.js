/* 异步显示缓存：核验去重、版本隔离、淘汰和过期请求，避免返回错模型的图。 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');

(async () => {
  const elements = new Map(), requests = [], revoked = [];
  let nextUrl = 0, failNext = false, delayed = null, queuedNext = false;
  const $ = id => {
    if (!elements.has(id)) {
      const classes = new Set();
      elements.set(id, {value:'', src:'', textContent:'', classList:{
        add:c=>classes.add(c), remove:c=>classes.delete(c),
        toggle:(c,on)=>on ? classes.add(c) : classes.delete(c)}});
    }
    return elements.get(id);
  };
  class BlobURL extends URL {
    static createObjectURL() { return 'blob:test-' + ++nextUrl; }
    static revokeObjectURL(url) { revoked.push(url); }
  }
  const context = {$, document:{getElementById:$}, URL:BlobURL, URLSearchParams, AbortController, console,
    performance:require('node:perf_hooks').performance, setTimeout, clearTimeout, DOMException,
    fetch:async (url, options) => {
      requests.push({url, signal:options.signal});
      const gate = delayed; delayed = null;
      if (gate) await gate;
      if (queuedNext) { queuedNext=false; return {ok:true,status:202,json:async()=>({state:'running',message:'正在绘图'})}; }
      const ok = !failNext; failNext = false;
      return {ok, status:ok?200:409, json:async()=>({message:'绘图失败'}), blob:async()=>({size:800000})};
    }};
  vm.createContext(context);
  const source = fs.readFileSync(path.join(__dirname,'../web/static/app.js'),'utf8');
  vm.runInContext(source.slice(0,source.indexOf('function renderState()')), context);
  $('modelSource').value = 'model-a';
  let release;
  delayed = new Promise(resolve=>{release=resolve;});
  const first = vm.runInContext('loadFigure()', context);
  const duplicate = vm.runInContext('loadFigure()', context);
  assert.equal(requests.length,1); release(); await Promise.all([first,duplicate]);
  await vm.runInContext('loadFigure()',context);
  assert.equal(requests.length,1,'重复查看必须复用缓存');
  await vm.runInContext("figure='peaks';loadFigure()",context);
  await vm.runInContext("figure='importance';loadFigure()",context);
  assert.equal(vm.runInContext('figureCache.size',context),2,'按字节上限淘汰最旧图表');
  assert.ok(revoked.includes('blob:test-1'));
  $('modelSource').value = 'model-b';
  await vm.runInContext('loadFigure()',context);
  assert.equal(vm.runInContext('figureCache.size',context),1);
  // 202是后台任务状态，不可当PNG缓存；完成后只保存真正的图片。
  vm.runInContext('clearTrainingFigureCache()',context); queuedNext=true;
  const count=requests.length;
  await vm.runInContext('loadFigure()',context);
  assert.equal(requests.length,count+2);
  assert.equal(vm.runInContext('figureCache.size',context),1);
  assert.equal($('figureVersion').textContent,'模型版本 model-b');
  // 已被取消的旧响应即使仍然到达，也不能覆盖新模型。
  delayed = new Promise(resolve=>{release=resolve;});
  const stale = vm.runInContext("figure='peaks';loadFigure()",context);
  $('modelSource').value = 'model-c';
  await vm.runInContext('loadFigure()',context);
  const currentSrc = $('trainingFigure').src;
  release(); await stale;
  assert.equal($('trainingFigure').src,currentSrc);
  assert.equal($('figureVersion').textContent,'模型版本 model-c');
  assert.ok(requests[requests.length-2].signal.aborted);
  vm.runInContext('clearTrainingFigureCache()',context);
  failNext = true;
  await vm.runInContext('loadFigure()',context);
  assert.equal(vm.runInContext('figureCache.size',context),0,'失败响应不能进入缓存');
  await vm.runInContext('loadFigure()',context);
  assert.equal(vm.runInContext('figureCache.size',context),1);
  console.log('PASS: duplicate requests, bounded image cache, model isolation, stale cancellation and retry.');
})().catch(error=>{console.error(error);process.exit(1);});
