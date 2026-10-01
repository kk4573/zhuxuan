/* 竹喧 · 公共基础
 * 全局状态、小工具（请求 / 提示 / 朗读 / 输入法）、视图切换、统计、公共弹层绑定。
 * 按 /js/base.js → study.js / lib.js / settings.js → main.js 的顺序加载（普通脚本，非模块）。
 */

'use strict';

/* ============================================================
   竹喧 · 前端逻辑
   判定规则全部在后端（/api/session/answer），前端只负责展示，
   保证规则只有一份，不会前后端不一致。
   ============================================================ */

const $ = (sel) => document.querySelector(sel);

const S = {
  view: 'study',
  phase: 'ready',
  sessionId: null,
  queue: [],          // 本轮题目（答错的会塞回队尾，所以会变长）
  idx: 0,
  submitted: false,
  auto: false,
  autoTimer: null,
  total: 0,           // 本轮抽到多少个不同的词
  done: new Set(),    // 已经答对的词 id
  asked: 0,           // 本轮总作答次数（含重考）
  wrongWords: [],     // 首答没答对的词
  stats: null,
};

let wordCache = {};
let editingId = null;
let toastTimer = null;

/* ==================== 小工具 ==================== */

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (e) { /* 无响应体 */ }
  if (!res.ok) {
    const d = data && (data.detail || data.message);
    throw new Error(typeof d === 'string' ? d : ('HTTP ' + res.status));
  }
  return data;
}

// 加词时的自动填充规则：什么时候允许用查词结果覆盖某个字段？
//   · 字段是空的        → 覆盖
//   · 字段里的值是上次自动查来的 → 覆盖（用户还在接着打这个单词，释义要跟着更新）
//   · 用户自己动手改过  → 不覆盖
// 这样「打 cry 停一下（查到 cry）→ 继续打成 crystal」也能拿到 crystal 的释义。
function shouldFill(autoFilled, key, currentValue) {
  return autoFilled[key] === true || !String(currentValue == null ? '' : currentValue).trim();
}

const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function toast(text, kind) {
  const el = $('#toast');
  el.textContent = text;
  el.className = 'toast' + (kind ? ' ' + kind : '');
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 3400);
}

// 应用内风格的确认弹窗（浏览器自带的 confirm 太出戏）
let confirmResolve = null;

function askConfirm(title, text, okText) {
  $('#confirmTitle').textContent = title;
  $('#confirmText').textContent = text;
  $('#confirmOk').textContent = okText || '确定';
  $('#confirmModal').hidden = false;
  setTimeout(() => $('#confirmOk').focus(), 0);
  return new Promise((resolve) => { confirmResolve = resolve; });
}

function closeConfirm(val) {
  $('#confirmModal').hidden = true;
  if (confirmResolve) { const r = confirmResolve; confirmResolve = null; r(val); }
}

function msg(sel, text, kind) {
  const el = $(sel);
  el.textContent = text;
  el.className = 'modalmsg' + (kind ? ' ' + kind : '');
}

let currentAudio = null;

// 优先用有道真人发音（/api/audio 后端代理），取不到再退回本机合成音
function speak(text) {
  try {
    if (currentAudio) { currentAudio.pause(); currentAudio = null; }
    const a = new Audio('/api/audio/' + encodeURIComponent(text));
    currentAudio = a;
    let fell = false;
    const fallback = () => { if (!fell) { fell = true; tts(text); } };
    a.addEventListener('error', fallback);
    const pr = a.play();
    if (pr && pr.catch) pr.catch(fallback);
  } catch (e) { tts(text); }
}

function tts(text) {
  try {
    if (!('speechSynthesis' in window)) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = 'en-US';
    u.rate = 0.85;
    window.speechSynthesis.speak(u);
  } catch (e) { /* 没有语音就静默跳过 */ }
}

// 答题时把输入法切到英文，离开时还原（后端调 Win32；失败也不打断答题）
async function setIme(on) {
  try { await api('POST', '/api/ime', { on: on }); } catch (e) { /* 静默 */ }
}

/* ==================== 回到最顶部的悬浮球 ==================== */

// 词库里往下滑了一段之后才露面（列表短的时候不打扰）
function syncGoTop() {
  const btn = $('#goTop');
  if (!btn) return;
  btn.classList.toggle('show', S.view === 'lib' && window.scrollY > 240);
}

window.addEventListener('scroll', syncGoTop, { passive: true });
$('#goTop').onclick = () => window.scrollTo({ top: 0, behavior: 'smooth' });

/* ==================== 视图 / 阶段 ==================== */

function showView(v) {
  S.view = v;
  try { if (location.hash !== '#' + v) history.replaceState(null, '', '#' + v); } catch (e) { /* 无所谓 */ }
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.dataset.view === v));
  $('#view-study').hidden = v !== 'study';
  $('#view-lib').hidden = v !== 'lib';
  $('#view-look').hidden = v !== 'look';
  if (v === 'lib') { loadWords(); if (S.phase === 'quiz') setIme(false); }
  syncGoTop();
  if (v === 'look') setTimeout(() => $('#lookInput').focus(), 0);
  if (v === 'study' && S.phase === 'quiz') {
    setIme(true);                     // 从词库切回来要重新锁英文（离开时被还原成中文了）
    setTimeout(() => $('#qInput').focus(), 0);
  }
}

function showPhase(p) {
  S.phase = p;
  $('#study-ready').hidden = p !== 'ready';
  $('#study-quiz').hidden = p !== 'quiz';
  $('#study-done').hidden = p !== 'done';
}

/* ==================== 统计 ==================== */

async function loadStats() {
  loadBooks().then(() => { if (!$('#studyBook') || !$('#studyBook').value) refreshBookSelects(); });
  try {
    const s = await api('GET', '/api/stats');
    S.stats = s;
    $('#hud').innerHTML = '<div>词库<b>' + s.total + '</b></div>';
    const eb = $('#enrichBtn');
    if (eb) {
      if (s.no_cn_pending > 0) { eb.hidden = false; eb.textContent = '补全释义（' + s.no_cn_pending + ' 个）'; }
      else { eb.hidden = true; }
    }
    renderReadyHint();
  } catch (e) {
    toast('读取统计失败：' + e.message, 'bad');
  }
}

function renderReadyHint() {
  const s = S.stats;
  if (!s) return;
  if (!s.total) {
    $('#readyHint').innerHTML = '词库为空，请先在「词库」页导入单词';
    return;
  }
  if (s.total === s.no_cn) {
    $('#readyHint').innerHTML = '词库里 <b>' + s.total + '</b> 个单词均缺少中文释义，无法出题';
    return;
  }
  let html = '词库共 <b>' + s.total + '</b> 个单词　·　已精通 ' + s.mastered +
             '　·　学习中 ' + s.learning + '　·　未练习 ' + s.fresh;
  if (s.no_cn) html += '<br><span class="warn">其中 ' + s.no_cn + ' 个单词缺少中文释义，不会出现在题目中</span>';
  $('#readyHint').innerHTML = html;
}


/* ==================== 公共弹层的绑定 ==================== */

function bindCore() {

  // 确认弹窗
  $('#confirmOk').onclick = () => closeConfirm(true);
  $('#confirmCancel').onclick = () => closeConfirm(false);

  // 点弹层背景关闭
  // 点弹层背景关闭
  document.querySelectorAll('.modal').forEach((m) => {
    m.addEventListener('mousedown', (e) => {
      if (e.target !== m) return;
      if (m.id === 'confirmModal') closeConfirm(false); else m.hidden = true;
    });
  });

  // 直接关窗口时，尽量把输入法还原回去
  // 直接关窗口时，尽量把输入法还原回去
  window.addEventListener('beforeunload', () => {
    if (S.phase === 'quiz' && navigator.sendBeacon) {
      navigator.sendBeacon('/api/ime',
        new Blob([JSON.stringify({ on: false })], { type: 'application/json' }));
    }
  });
}
