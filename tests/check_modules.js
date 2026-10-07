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
    appendChild() {}, contains() { return true; }, closest() { return null; },
    querySelector() { return makeEl(); },
    querySelectorAll() { return []; }, scrollIntoView() {}, removeAttribute() {}, setAttribute() {},
    // 弹框定位要用；缺了它 placeWordPop 会抛错，后面的断言就全是假的（踩过）
    getBoundingClientRect() { return { left: 10, top: 10, right: 70, bottom: 32, width: 60, height: 22 }; },
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
    removeEventListener() {},
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



// ---------- 例句里的词高亮 ----------
console.log('\n— 例句高亮目标词 —');
try {
  const cases = [
    ['The captain gave the order to abandon ship.', 'abandon', 1],
    ['The odours filled the room.', 'odour', 1],              // 复数也要标
    ['He abandoned his car.', 'abandon', 1],                  // 过去式也要标
    ['A crystal clear lake.', 'cry', 0],                      // 不能误伤 crystal
    ['The desert was vast.', 'desert', 1],
    ['Nothing here at all.', 'abandon', 0],
  ];
  let allOk = true;
  for (const [sent, word, want] of cases) {
    const got = vm.runInContext('markWord(' + JSON.stringify(sent) + ',' + JSON.stringify(word) + ')', ctx);
    const n = (got.match(/class="qhit"/g) || []).length;
    if (n !== want) {
      allOk = false;
      check('高亮 ' + word + ' @ ' + sent.slice(0, 24) + ' (期望 ' + want + '，实得 ' + n + ')', false, got);
    }
  }
  check('例句高亮：6 个用例全对', allOk);

  // 转义顺序：先 esc 再替换，正文里的尖括号不能被当标签
  const esc1 = vm.runInContext('markWord("<b>abandon</b> & co", "abandon")', ctx);
  check('例句高亮：尖括号被正确转义', esc1.includes('&lt;b&gt;') && !esc1.includes('<b>abandon'), esc1);

  // 空词不能炸
  const esc2 = vm.runInContext('markWord("hello world", "")', ctx);
  check('例句高亮：空单词安全', esc2 === 'hello world');
} catch (e) {
  check('例句高亮能跑', false, String(e));
}


// ---------- 例句里点单词弹出的小框 ----------
console.log('\n— 点词弹框 —');
const popChecks = [];
try {
  vm.runInContext('bindWordPop()', ctx);
  check('bindWordPop() 能正常执行', true);
} catch (e) {
  check('bindWordPop() 能正常执行', false, String(e));
}

try {
  // tokenizeSentence：每个词都要能点，答案那个额外高亮
  const html = vm.runInContext(`tokenizeSentence('SO2 is a colourless gas with a sharp odour.', 'odour')`, ctx);
  const words = [...html.matchAll(/data-w="([^"]*)"/g)].map((m) => m[1]);
  check('例句切出 9 个可点的词', words.length === 9, words);
  check('答案词带高亮标记', html.includes('wd qhit'),
        (html.match(/class="wd[^"]*"/g) || []).join(' '));
  check('标点不进词里（结尾的句号单独）', !words.includes('odour.'), words.slice(-2));

  // 变形词高亮：odours 应该也算 odour 那个答案
  const h2 = vm.runInContext(`tokenizeSentence('The odours were strong.', 'odour')`, ctx);
  check('变形词也算同一个答案（odours 高亮）', (h2.match(/wd qhit/g) || []).length === 1, h2);

  // 两次切词不能把转义搞坏
  const h3 = vm.runInContext(`tokenizeSentence('a < b & c', 'a')`, ctx);
  check('例句里的特殊符号被转义', h3.includes('&lt;') && h3.includes('&amp;'), h3);
} catch (e) {
  check('tokenizeSentence 能跑', false, String(e));
}



try {
  // 1) 事件委托：点 .wd 应该认出来并交给 openWordPop
  const fakeSpan = makeEl('span');
  fakeSpan.dataset = { w: 'colourless' };
  const evt = {
    target: { closest: (sel) => (sel === '.wd[data-w]' ? fakeSpan : null) },
    preventDefault() {}, stopPropagation() {},
  };
  const docClick = listeners.filter((l) => l[0] === 'document:click').map((l) => l[1]).pop();
  check('bindWordPop 挂上了 document 的 click 监听', typeof docClick === 'function',
        listeners.map((l) => l[0]));

  const oldFetch = sandbox.fetch;
  sandbox.fetch = async () => ({
    ok: true, status: 200,
    json: async () => ({ ok: true, en: 'colourless', form: 'colourless',
                         cn: 'adj. 无色的', pos: 'adj.', ph: 'kʌlələs', in_library: false }),
  });

  // 2) 直接调 openWordPop（比走点击链路稳，不依赖假 DOM 的事件冒泡细节）
  sandbox.__span = fakeSpan;
  vm.runInContext('openWordPop(__span)', ctx);
  const pop = vm.runInContext('POP.el', ctx);
  check('点词之后弹框被创建', !!pop);
  check('点词之后弹框显示出来了（不是 hidden）', pop && pop.hidden === false, pop && pop.hidden);
  check('弹框里填了内容', pop && String(pop.innerHTML || '').length > 0,
        pop && String(pop.innerHTML).slice(0, 60));
  // 定位：placeWordPop 得真的算出一个坐标摆上去，不然框会叠在左上角
  check('弹框被摆到了某个坐标上', pop && pop.style && pop.style.left !== undefined
        && pop.style.left !== '' && pop.style.top !== '', pop && pop.style);

  // 3) 关掉之后要真的收起来
  vm.runInContext('closeWordPop()', ctx);
  check('关掉之后弹框是 hidden', pop && pop.hidden === true, pop && pop.hidden);

  // 3) 再走一遍"点别处就关"的链路
  if (typeof docClick === 'function') docClick(evt);
  sandbox.fetch = oldFetch;
} catch (e) {
  check('点词不会抛异常', false, String(e));
}


// ---------- 查词页的返回键（完整复现 kk 报的三层场景） ----------
console.log('\n— 返回键：词库 → 词A → 词B → 返回 → 返回 —');
try {
  const back = sandbox.document.querySelector('#lookBack');
  const oldFetch3 = sandbox.fetch;
  // 任何请求都当成功，我们只关心返回栈
  sandbox.fetch = async () => ({ ok: true, status: 200, json: async () => ({ ok: true }) });

  const stack = () => vm.runInContext('S.lookStack.length', ctx);
  const click = () => { if (typeof back.onclick === 'function') back.onclick(); };

  // ① 自己查词：栈空、无返回键
  vm.runInContext("S.lookStack = []; renderLookBack();", ctx);
  check('自己查的词：不显示返回键', back.hidden === true);

  // ② 从词库页点了一个词跳过来
  vm.runInContext("S.view='lib'; openLook('alpha', { type: 'view', view: 'lib' });", ctx);
  check('词库 → 词A：栈里有 1 层', stack() === 1, stack());
  check('词库 → 词A：返回键出现了', back.hidden === false);
  check('按钮文案是「← 返回」', back.textContent === '← 返回', back.textContent);

  // ③ 在查词页里又点了词B的「更多」（pop.js 会这么记）
  vm.runInContext("S.view='look'; lookWord='alpha';", ctx);
  vm.runInContext("openLook('beta', { type: 'word', word: 'alpha' });", ctx);
  check('词A → 词B：栈里有 2 层', stack() === 2, stack());

  // ④ 第一次返回 → 回到词A，**返回键还得在**（kk 报的就是这里没了）
  click();
  check('返回一次：回到词A', vm.runInContext('lookWord', ctx) === 'alpha',
        vm.runInContext('lookWord', ctx));
  check('返回一次后：栈剩 1 层', stack() === 1, stack());
  check('返回一次后：返回键还在（能继续退回词库）', back.hidden === false, back.hidden);

  // ⑤ 第二次返回 → 回到词库页，栈清空、返回键消失
  click();
  check('返回两次：回到词库页', vm.runInContext('S.view', ctx) === 'lib',
        vm.runInContext('S.view', ctx));
  check('返回两次后：栈空了', stack() === 0, stack());
  check('返回两次后：返回键消失', back.hidden === true, back.hidden);

  sandbox.fetch = oldFetch3;
} catch (e) {
  check('返回键三层场景能跑', false, String(e));
}

(async () => {
// ---------- 真去点一遍按钮：抓「回调里的引用错误」 ----------
// 这类错误语法检查抓不到（比如 res 声明在 else 块里、块外却用到），
// 只有在用户真点下去的那一刻才会炸成 "xxx is not defined"。这里替用户点。
console.log('\n— 点击回调能不能跑通 —');
const clickable = ['addBtn', 'editOk', 'importOk', 'editCancel', 'importCancel',
                   'searchClear', 'enrichBtn', 'importBtn'];
for (const id of clickable) {
  const el = sandbox.document.querySelector('#' + id);
  if (!el || typeof el.onclick !== 'function') {
    check('#' + id + ' 绑了点击回调', false, typeof (el && el.onclick));
    continue;
  }
  // 先把提示框清干净，免得读到上一轮的
  const boxes = ['#editMsg', '#importMsg', '#bookMsg', '#newBookMsg'];
  boxes.forEach((b) => { const x = sandbox.document.querySelector(b); if (x) x.textContent = ''; });
  // 关键：得把表单填上，否则回调在第一行「英文不能为空」就 return 了，
  // 后面真正的逻辑压根没跑 —— 测试会假绿（曾经就这么漏掉一个 ReferenceError）
  if (id === 'editOk') {
    sandbox.document.querySelector('#editEn').value = 'vacuum';
    sandbox.document.querySelector('#editCn').value = 'n. 真空';
  }
  if (id === 'importOk') {
    sandbox.document.querySelector('#importText').value = 'vacuum';
  }
  let threw = null;
  try {
    const r = el.onclick({ preventDefault() {}, target: makeEl() });
    if (r && typeof r.then === 'function') await r;
  } catch (e) {
    threw = e;
  }
  // 光"没抛异常"不够 —— 很多错误被 try/catch 吞掉，变成给用户看的红字提示。
  // 所以还要看提示框里有没有冒出来一个「XXX is not defined」之类的。
  const shown = boxes
    .map((b) => { const x = sandbox.document.querySelector(b); return x ? (x.textContent || '') : ''; })
    .join(' ');
  const looksLikeBug = /is not defined|is not a function|Cannot read|undefined is not/.test(shown);
  check('#' + id + ' 点下去没出错提示',
        !threw && !looksLikeBug,
        threw ? String(threw) : shown);
}

// ==================== 空词库时的首屏引导（朋友第一次打开就是这个状态）====================
{
  // S 是 const 声明的，vm 不会挂到 sandbox 上（只有 function 会），所以要在同一个
  // context 里用 runInContext 执行才能访问 S。
  const renderWith = (total, noCn) => vm.runInContext(`
    S.stats = { total: ${total}, no_cn: ${noCn}, mastered: 0, learning: 0, fresh: 0 };
    renderReadyHint();
    (() => {
      const b = $('#firstImportBtn');
      return {
        html: $('#readyHint').innerHTML || '',
        btnHidden: b ? b.hidden : null,
        hasHandler: b ? typeof b.onclick === 'function' : false,
      };
    })()
  `, ctx);

  const empty = renderWith(0, 0);
  const textEmpty = String(empty.html).replace(/<[^>]*>/g, '');
  check('空词库时说明可以导入内置词表', /内置词表/.test(textEmpty), textEmpty.slice(0, 140));
  check('空词库时不再只说"去词库页加词"', !/词库为空，先去/.test(textEmpty), textEmpty.slice(0, 80));
  check('空词库时「导入词表」按钮显示出来', empty.btnHidden === false, empty.btnHidden);
  check('「导入词表」按钮绑了点击回调', empty.hasHandler === true, empty.hasHandler);

  // 按钮得真能点：一点就跳到词库页
  const jump = vm.runInContext(`
    (() => {
      $('#view-lib').hidden = true; $('#view-study').hidden = false;
      const b = $('#firstImportBtn');
      if (typeof b.onclick !== 'function') return 'no-handler';
      b.onclick();
      return $('#view-lib').hidden === false ? 'jumped' : 'stuck';
    })()
  `, ctx);
  check('点「导入词表」会跳到词库页', jump === 'jumped', jump);

  const has = renderWith(8, 0);
  const textHas = String(has.html).replace(/<[^>]*>/g, '');
  check('有词时「导入词表」按钮收起来', has.btnHidden === true, has.btnHidden);
  check('有词时显示词量', /8/.test(textHas), textHas.slice(0, 100));
}

console.log(`\n结果：${ok} 通过 / ${fail} 失败`);
process.exit(fail ? 1 : 0);
})();
