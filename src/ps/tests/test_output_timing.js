'use strict';
const assert=require('node:assert/strict');
const {describe}=require('../web/static/output_timing.js');
assert.equal(describe({available:false}),null);
assert.equal(describe({available:true,timing_schema:'legacy'}),null);
const output={available:true,enabled:false,timing_schema:'active_windows_v1',windows:{period_ns:10000,
  laser:{segments_ns:[[0,5000]],wraps_cycle:false},gate:{segments_ns:[[0,800],[8800,10000]],wraps_cycle:true}}};
const result=describe(output);
assert.deepEqual(result.rows.gate,[{start:0,end:800,left:0,width:8},{start:8800,end:10000,left:88,width:12}]);
assert.equal(result.enabled,false);assert.equal(result.wraps,true);
const bad=JSON.parse(JSON.stringify(output));bad.windows.gate.segments_ns=[[9000,11000]];
assert.throws(()=>describe(bad),/窗口无效/);
console.log('PASS: low-active gate timeline, wrapping segments and disabled-state distinction');
