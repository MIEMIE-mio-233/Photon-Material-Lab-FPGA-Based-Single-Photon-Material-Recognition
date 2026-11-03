/* 网页使用正向码：数值越大，ATK 模块的模拟输出电压越高。
 * 驱动/API/PL 寄存器继续使用原始 DAC 码，只在网页读写边界换算。
 * 两个方向都采用 1023 - code，因此已有输出电平可以无损往返。
 */
(function () {
  'use strict';
  const MAX_CODE = 1023;

  function checkedCode(value) {
    if (!['number', 'string'].includes(typeof value) || String(value).trim() === '')
      throw new Error('DAC 正向码值必须是 0～1023 的整数');
    const code = Number(value);
    if (!Number.isInteger(code) || code < 0 || code > MAX_CODE)
      throw new Error('DAC 正向码值必须是 0～1023 的整数');
    return code;
  }

  const conversion = Object.freeze({
    toPositiveCode: rawCode => MAX_CODE - checkedCode(rawCode),
    toRawCode: positiveCode => MAX_CODE - checkedCode(positiveCode)
  });
  if (typeof module !== 'undefined' && module.exports) module.exports = conversion;
  if (typeof window !== 'undefined') window.DacLevels = conversion;
})();
