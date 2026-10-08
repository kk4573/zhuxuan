
/* 验证「检查更新」的前端行为 —— 重点是「查到新版本要显示」和「查不到要安静」。 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const WEB = path.join(__dirname, '..', 'web');
let pass = 0, fail = 0;
function check(name, cond) {
  if (cond) { console.log('  [ok]    ' + name); pass++; }
  else { console.log('  [FAIL]  ' + name); fail++; }
}

// ---- 造一个最小的 DOM + 依赖，把 base.js 跑起来
const bar = {
  hidden: true,
  _html: '',
};
const txt = { set innerHTML(v) { bar._html = v; }, get innerHTML() { return bar._html; } };
const howBtn = { onclick: null };
const closeBtn = { hidden: true, onclick: null };
const toasts = [];

const sandbox = {
  console,
  document: {
    querySelector(sel) {
      if (sel === '#updateBar') return bar;
      if (sel === '#updateText') return txt;
      if (sel === '#updateHow') return howBtn;
      if (sel === '#updateClose') return closeBtn;
      return null;
    },
    querySelectorAll() { return []; },
    addEventListener() {},
  },
  window: { addEventListener() {} },
  location: { hash: '' },
  setTimeout, clearTimeout,
  toast(msg) { toasts.push(msg); },
  // api() 由测试控制返回值
  __nextApiResult: null,
  __apiCalls: [],
};

sandbox.globalThis = sandbox;
vm.createContext(sandbox);

// 先注入 api()（base.js 里会用到）
vm.runInContext(`
  var __apiImpl = null;
  function api(method, url, body) {
    __apiCalls.push([method, url]);
    return Promise.resolve(__apiImpl);
  }
  function esc(s) { return String(s); }
  function $(sel) { return document.querySelector(sel); }
`, sandbox);

// 加载真实的 base.js（只取 checkUpdate 那段）
const baseSrc = fs.readFileSync(path.join(WEB, 'js', 'base.js'), 'utf8');
const start = baseSrc.indexOf('async function checkUpdate');
if (start < 0) { console.log('  [FAIL]  找不到 checkUpdate'); process.exit(1); }
// 截到它的结束（下一个顶层 function）
let end = baseSrc.indexOf('\nasync function ', start + 10);
let end2 = baseSrc.indexOf('\nfunction ', start + 10);
if (end < 0) end = end2;
if (end2 >= 0 && (end < 0 || end2 < end)) end = end2;
if (end < 0) end = baseSrc.length;
const fnSrc = baseSrc.slice(start, end);

vm.runInContext(fnSrc, sandbox);

(async () => {
  console.log('=== 场景①：查到了更新的版本 → 应该显示提示条 ===');
  vm.runInContext(`__apiImpl = { current: '1.1.1', latest: '1.2.0', has_update: true, checked: true };`, sandbox);
  await vm.runInContext('checkUpdate()', sandbox);
  check('提示条显示出来了', bar.hidden === false);
  check('提示里写了新版本号', bar._html.includes('1.2.0'));
  check('提示里写了当前版本', bar._html.includes('1.1.1'));
  check('提示了数据不会丢', bar._html.includes('不会丢') || bar._html.includes('数据'));

  console.log('\n=== 场景②：已经是最新版 → 不显示 ===');
  bar.hidden = true;
  vm.runInContext(`__apiImpl = { current: '1.1.1', latest: '1.1.1', has_update: false, checked: true };`, sandbox);
  await vm.runInContext('checkUpdate()', sandbox);
  check('提示条保持隐藏', bar.hidden === true);

  console.log('\n=== 场景③：查不到（断网/被墙/404）→ 不显示、不报错 ===');
  bar.hidden = true;
  vm.runInContext(`__apiImpl = { current: '1.1.1', latest: null, has_update: false, checked: true, error: 'HTTP Error 404' };`, sandbox);
  let threw = false;
  try { await vm.runInContext('checkUpdate()', sandbox); } catch (e) { threw = true; }
  check('没有抛异常', !threw);
  check('提示条保持隐藏', bar.hidden === true);

  console.log('\n=== 场景④：接口整个挂了（抛异常）→ 也不能崩 ===');
  bar.hidden = true;
  vm.runInContext(`__apiImpl = null; __apiThrows = true;`, sandbox);
  vm.runInContext(`
    api = function(){ return Promise.reject(new Error('boom')); };
  `, sandbox);
  threw = false;
  try { await vm.runInContext('checkUpdate()', sandbox); } catch (e) { threw = true; }
  check('没有抛异常（否则会污染整个页面）', !threw);
  check('提示条保持隐藏', bar.hidden === true);

  console.log('\n=== 场景⑤：点「知道了」能关掉 ===');
  vm.runInContext(`api = function(m,u){ __apiCalls.push([m,u]); return Promise.resolve({ current:'1.1.1', latest:'1.2.0', has_update:true, checked:true }); };`, sandbox);
  await vm.runInContext('checkUpdate()', sandbox);
  check('提示条显示了', bar.hidden === false);
  check('「知道了」按钮绑了事件', typeof closeBtn.onclick === 'function');
  if (typeof closeBtn.onclick === 'function') {
    closeBtn.onclick();
    check('点了之后关掉了', bar.hidden === true);
  }

  console.log(`\n结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail > 0 ? 1 : 0);
})();
