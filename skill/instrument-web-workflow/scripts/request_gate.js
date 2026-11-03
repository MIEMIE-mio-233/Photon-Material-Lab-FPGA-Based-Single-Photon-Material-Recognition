/* 通用请求身份门控。仅决定是否可提交结果，不执行网络或DOM操作。 */
'use strict';
class RequestGate {
  constructor() { this.epoch=0; this.current=null; }
  begin(key) {
    if(typeof key!=='string'||!key.length)throw new TypeError('request key must be nonempty');
    this.current=Object.freeze({epoch:++this.epoch,key});
    return this.current;
  }
  accepts(token) { return token===this.current && token!==null; }
  cancel() { ++this.epoch;this.current=null; }
}
if(typeof module!=='undefined')module.exports={RequestGate};
