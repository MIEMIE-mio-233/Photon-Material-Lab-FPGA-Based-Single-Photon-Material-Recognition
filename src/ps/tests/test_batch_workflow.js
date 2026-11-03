/* 组合筛选、未知元数据、时间排序与训练选择；不访问板卡。 */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const context={};vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/static/batch_picker.js'),'utf8'),context);
const rows=[
 {id:'run_20261023_120000_x',key:'a',material:'fe',materials:['fe'],specimen:'fe_01',distance_cm:15,illumination:'shielded'},
 {id:'run_20261024_100000_x',key:'b',material:'fe',materials:['fe'],specimen:'fe_02',distance_cm:15,illumination:'partial'},
 {id:'run_20261024_110000_x',key:'c',material:'pp',materials:['pp'],specimen:'pp_01',distance_cm:null,illumination:null}];
context.rows=rows;
assert.equal(vm.runInContext('newestRuns(rows)[0].key',context),'c');
context.filter={search:'FE_02',date:'2026-10-24',material:'fe',specimen:'fe_02',distance:'15',light:'partial'};
assert.equal(vm.runInContext('rows.filter(row=>batchMatches(row,filter)).map(row=>row.key).join()',context),'b');
context.filter={light:'unknown',distance:'unknown'};
assert.equal(vm.runInContext('rows.filter(row=>batchMatches(row,filter)).map(row=>row.key).join()',context),'c');
context.filter={date:'2026-10-24',material:'fe',specimen:'fe_01'};
assert.equal(vm.runInContext('rows.filter(row=>batchMatches(row,filter)).length',context),0);
const html=fs.readFileSync(path.join(__dirname,'../web/static/index.html'),'utf8');
assert.ok(!html.includes('id="interval"'));assert.ok(!html.includes('data-mode="fingerprint"'));
for(const id of ['auxiliaryRecords','captureModelSelect','selectOnlyFilteredRuns','compareSmallMultiples','comparisonFeatures'])assert.ok(html.includes('id="'+id+'"'));
for(const prefix of ['dataBatch','trainBatch'])for(const key of ['Search','Date','Material','Specimen','Light','Distance'])assert.ok(html.includes('id="'+prefix+key+'"'));
console.log('PASS: compound filters, unknown values, newest first and required workflow controls.');
