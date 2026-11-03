/* 公共交互：确认弹窗、按钮反馈和下拉框关闭规则。完全离线，无第三方脚本。 */
'use strict';
let confirmationPending = null;

function confirmAction({title, message, confirmLabel = '确认删除'}) {
  const dialog = $('confirmDialog');
  if (!dialog || typeof dialog.showModal !== 'function') return Promise.resolve(window.confirm(`${title}\n\n${message}`));
  if (confirmationPending) return Promise.resolve(false);
  $('confirmTitle').textContent = title;
  $('confirmMessage').textContent = message;
  $('confirmAccept').textContent = confirmLabel;
  dialog.returnValue = 'cancel'; dialog.showModal();
  return new Promise(resolve => { confirmationPending = resolve; });
}

function buttonProgress(button, label) {
  if (!button) return () => {};
  const original = button.textContent;
  button.textContent = label; button.setAttribute('aria-busy', 'true');
  return () => { button.textContent = original; button.removeAttribute('aria-busy'); };
}

function selectDataFrame(path) {
  // 最新临时帧也要在公共文件框中明确显示，不能与实际展示的帧不一致。
  const known = dataset.frames.find(item => item.path === path);
  if (known && $('runSelect').value && $('runSelect').value !== known.run_key) {
    $('runSelect').value = ''; fillFrames();
  }
  if (![...$('frameSelect').options].some(option => option.value === path)) {
    $('frameSelect').appendChild(new Option(path.startsWith('memory/') ? '最新采集帧 · 未保存' : frameCaption(path), path));
  }
  $('frameSelect').value = path;
  $('selectedPath').textContent = path.startsWith('memory/') ? '最新采集帧 · 仅保存在内存中' : path;
}

function initializeUiControls() {
  const dialog = $('confirmDialog');
  dialog.addEventListener('close', () => {
    const resolve = confirmationPending; confirmationPending = null;
    if (resolve) resolve(dialog.returnValue === 'confirm');
  });
  // 原生details支持键盘打开；所有多选框使用相同的外点和Esc关闭规则。
  const pickers = [...document.querySelectorAll('.batch-picker')];
  pickers.forEach(picker => picker.addEventListener('toggle', () => {
    if (picker.open) pickers.forEach(other => { if (other !== picker) other.open = false; });
  }));
  document.addEventListener('click', event => pickers.forEach(picker => { if (!picker.contains(event.target)) picker.open = false; }));
  document.addEventListener('keydown', event => { if (event.key === 'Escape') pickers.forEach(picker => { picker.open = false; }); });
}
