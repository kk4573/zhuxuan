/**
 * 竹喧 · 前端模块加载测试
 *
 * 把 web/js/*.js 按 index.html 里的顺序，在一个「假 DOM」里真跑一遍。
 * 拆文件最容易出的错就是「运行时才炸」的引用问题（顺序不对、函数搬丢了、
 * 变量在定义前被用到），静态检查看不出来，这个脚本能抓住。
 *
 *     node tests/check_modules.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.join(__dirname, '..');
const HTML = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');

// 从 index.html 里按真实加载顺序取出 js 文件
const order = [...HTML.matchAll(/src="\/js\/([^"]+)"/g)].map((m) => m[1]);
if (!order.length) {
  console.error('index.html 里没有引用任何 /js/*.js');
  process.exit(1);
}

let ok = 0, fail = 0;
function check(label, cond, extra) {
  if (cond) { ok++; console.log('  [ok]    ' + label); }
  else { fail++; console.log('  [FAIL]  ' + label + '   ' + JSON.stringify(extra)); }
}

// ---------- 假 DOM：任何属性访问都返回一个「万能元素」 ----------
function makeEl(id) {
  const el = {
    id: id || '',
    value: '',
    textContent: '',
    innerHTML: '',
    hidden: false,
    disabled: false,
    readOnly: false,
    className: '',
    dataset: {},
    style: {},
    files: [],
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener() {}, removeEventListener() {}, focus() {}, blur() {}, click() {},
    appendChild() {}, closest() { return null; }, querySelector() { return makeEl(); },
    querySelectorAll() { return []; }, scrollIntoView() {}, removeAttribute() {},
  };
  // 访问未知属性时也给个元素，避免任何一处 null 炸掉
  el.parentElement = el;      // 自指，省得递归创建（代码里只用到一层）
  el.children = [];
  return new Proxy(el, {
    get(t, k) {
      if (k in t) return t[k];
      if (typeof k === 'string' && /^[a-z]/.test(k)) return undefined;
      return makeEl();
    },
    set(t, k, v) { t[k] = v; return true; },
  });
}

const listeners = [];
const elStore = {};   // 让 querySelector 返回同一个元素，才能读回 innerHTML
const sandbox = {
  console,
  setTimeout, clearTimeout, setInterval, clearInterval,
  JSON, Math, Date, Object, Array, String, Number, Boolean, RegExp, Error, Promise, Map, Set,
  encodeURIComponent, decodeURIComponent, parseInt, parseFloat, isNaN,
  document: {
    body: makeEl('body'),
    documentElement: makeEl('html'),
    activeElement: null,
    querySelector: (s) => (elStore[s] = elStore[s] || makeEl(s)),
    querySelectorAll: () => [],
    addEventListener: (t, fn) => listeners.push(['document:' + t, fn]),
    createElement: () => makeEl(),
  },
  window: {
    scrollY: 0,
    addEventListener: (t, fn) => listeners.push(['window:' + t, fn]),
    scrollTo() {}, matchMedia: () => ({ matches: false, addEventListener() {} }),
  },
  navigator: { sendBeacon: () => true, userAgent: 'node' },
  location: { href: 'http://127.0.0.1:8765/', origin: 'http://127.0.0.1:8765' },
  fetch: async () => ({ ok: true, status: 200, json: async () => ({}) }),
  Blob: function () {},
  FormData: function () { this.append = () => {}; },
  Audio: function () { this.play = () => Promise.resolve(); },
  speechSynthesis: { speak() {}, cancel() {}, getVoices: () => [] },
  SpeechSynthesisUtterance: function () {},
};
sandbox.window.document = sandbox.document;
sandbox.globalThis = sandbox;

const ctx = vm.createContext(sandbox);

console.log('加载顺序（取自 index.html）：');
order.forEach((f, i) => console.log(`  ${i + 1}. ${f}`));
console.log('');

// ---------- 逐个文件执行，模拟浏览器的脚本加载 ----------
const loaded = [];
for (const f of order) {
  const full = path.join(ROOT, 'web', 'js', f);
  if (!fs.existsSync(full)) { check(`文件存在：${f}`, false); continue; }
  const code = fs.readFileSync(full, 'utf8');
  try {
    vm.runInContext(code, ctx, { filename: f });
    loaded.push(f);
    check(`${f} 执行通过`, true);
  } catch (e) {
    check(`${f} 执行通过`, false, e.message);
  }
}
check(`全部 ${order.length} 个文件都加载成功`, loaded.length === order.length, loaded);

// ---------- 关键函数是否都真的定义出来了 ----------
console.log('');
const need = ['api', 'toast', 'msg', 'speak', 'setIme', 'showView', 'showPhase',
              'loadStats', 'startSession', 'submit', 'checkRetype', 'checkOtherWord',
              'renderQuestion', 'nextQuestion', 'finishSession', 'loadWords',
              'renderWords', 'renderPager', 'openEdit', 'runEnrich', 'openPrev',
              'openSettings', 'saveSettings', 'askConfirm', 'closeConfirm',
              'shouldFill', 'syncGoTop', 'init',
              'bindCore', 'bindStudy', 'bindLib', 'bindSettings', 'bindTabs'];
const missing = need.filter((n) => typeof ctx[n] !== 'function');
check(`关键的 ${need.length} 个函数都挂上了`, missing.length === 0, missing);

// ---------- 每个 bind 函数单独调用一次，确认里面的元素引用不炸 ----------
console.log('');
for (const fn of ['bindTabs', 'bindCore', 'bindStudy', 'bindLib', 'bindSettings']) {
  try {
    ctx[fn]();
    check(`${fn}() 能正常执行`, true);
  } catch (e) {
    check(`${fn}() 能正常执行`, false, e.message);
  }
}

// ---------- init 已经被自动调用过（main.js 末尾） ----------
check('main.js 末尾自动执行了 init()', loaded.includes('main.js'));


// ---------- 词库管理弹层：默认词库不能被删 ----------
console.log('\n— 词库管理弹层的按钮 —');
try {
  vm.runInContext(`
    BOOKS = [
      { id: 1, name: '我的词库', count: 189, is_default: 1, builtin: '' },
      { id: 2, name: '考研词汇', count: 5392, is_default: 0, builtin: 'NPEE' },
    ];
    renderBookList();
  `, ctx);
  const out = sandbox.document.querySelector('#bookList').innerHTML;

  // 拆成行来看各自的按钮
  const rows = out.split('class="bookrow"').slice(1);
  const opsOf = (r) => [...r.matchAll(/data-op="(\w+)"/g)].map((m) => m[1]);
  const rDefault = rows.find((r) => r.includes('我的词库')) || '';
  const rOther = rows.find((r) => r.includes('考研词汇')) || '';
  const dOps = opsOf(rDefault), oOps = opsOf(rOther);

  check('默认词库有「默认」标记', rDefault.includes('bdft'));
  check('默认词库不给「删除」', !dOps.includes('del'), dOps);
  check('默认词库不给「设为默认」', !dOps.includes('default'), dOps);
  check('默认词库仍可「改名」', dOps.includes('rename'), dOps);
  check('普通词库有「删除」', oOps.includes('del'), oOps);
  check('普通词库有「设为默认」', oOps.includes('default'), oOps);
  check('内置词表标出来源', rOther.includes('NPEE'));
} catch (e) {
  check('词库管理渲染没炸', false, String(e));
}

console.log(`\n结果：${ok} 通过 / ${fail} 失败`);
process.exit(fail ? 1 : 0);
