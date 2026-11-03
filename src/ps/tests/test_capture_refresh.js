/* 真实采集进度不请求全量目录；列表变化在需要浏览时刷新。 */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[2] || require('node:path').join(__dirname,'../web/static/app.js'),'utf8');
const fn=source.match(/function shouldRefreshDataset\(data\) \{[\s\S]*?\n\}/)[0];
const c={dataDirty:false,dataSignature:'',panel:'capture',busy:true};c.active=()=>c.busy;vm.createContext(c);vm.runInContext(fn,c);
c.data={frame_count:100,specimen_count:14};const run=()=>vm.runInContext('shouldRefreshDataset(data)',c);
assert.equal(run(),false);
for(let i=1;i<50;i++){c.data.job_completed=i;assert.equal(run(),false)}
c.data.frame_count=101;assert.equal(run(),false);assert.equal(c.dataDirty,true);
c.busy=false;assert.equal(run(),false);c.panel='data';assert.equal(run(),true);
c.dataDirty=false;assert.equal(run(),false);c.data.frame_count=102;c.panel='train';assert.equal(run(),true);
console.log('PASS: no per-frame catalog request, deferred refresh and training/data visibility.');
