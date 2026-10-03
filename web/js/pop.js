/* 竹喧 · 例句里点单词弹出来的小框
 *
 * 例句里每个词都能点，点了**不跳转页面**，而是在那个词的位置弹一个小框，
 * 里面是这个单词最主要的一条释义，外加：
 *   · 🔊 发音
 *   · 更多 → 跳查词页看完整资料
 *   · ＋ 加入词库 → 直接进**默认词库**（不弹选择，kk 要求的）
 *
 * 后端会先把变形还原成原型（odours → odour、abandoned → abandon），
 * 所以点变形词也能拿到对的释义。
 */

let POP = { el: null, seq: 0, at: null };


/** 例句里的一个词要不要高亮（是不是这次考的那个，允许常见词尾变化）。 */
function isAnswerForm(token, answer) {
  const t = (token || '').toLowerCase();
  const a = (answer || '').toLowerCase();
  if (!t || !a) return false;
  if (t === a) return true;
  if (!t.startsWith(a)) return false;
  return /^(s|es|ed|d|ing|ly|er|est)$/.test(t.slice(a.length));
}


/**
 * 把一句例句切成「可点的词 + 其它」。
 *
 * 注意是**逐段转义**，不是先把整句转义再切 —— 后者会把 `&lt;` 里的分号也当成词边界。
 * 返回 HTML 字符串，调用方直接塞进 innerHTML。
 */
function tokenizeSentence(sent, answer) {
  const parts = String(sent || '').split(/([A-Za-z][A-Za-z'\u2019-]*)/);
  let out = '';
  for (const p of parts) {
    if (!p) continue;
    if (/^[A-Za-z]/.test(p)) {
      const cls = isAnswerForm(p, answer) ? 'wd qhit' : 'wd';
      out += '<span class="' + cls + '" data-w="' + esc(p) + '">' + esc(p) + '</span>';
    } else {
      out += esc(p).replace(/\n/g, ' ');
    }
  }
  return out;
}


/* ---------------- 小框本身 ---------------- */

function ensureWordPop() {
  if (POP.el && document.body.contains(POP.el)) return POP.el;
  const el = document.createElement('div');
  el.className = 'wordpop';
  el.id = 'wordPop';
  el.hidden = true;
  document.body.appendChild(el);
  POP.el = el;
  return el;
}


function closeWordPop() {
  if (POP.el) POP.el.hidden = true;
  POP.at = null;
  POP.seq += 1;                     // 让在途的请求作废
}


/** 把框摆在某个词旁边；靠近右/下边缘时自动翻到另一侧。 */
function placeWordPop(el, span) {
  const r = span.getBoundingClientRect();
  const w = el.offsetWidth || 300;
  const h = el.offsetHeight || 150;
  const pad = 8;

  let left = r.left;
  if (left + w + pad > window.innerWidth) left = window.innerWidth - w - pad;
  if (left < pad) left = pad;

  let top = r.bottom + 6;                       // 默认放在词的下方
  if (top + h + pad > window.innerHeight) {
    const above = r.top - h - 6;
    top = above > pad ? above : Math.max(pad, window.innerHeight - h - pad);
  }
  el.style.left = Math.round(left) + 'px';
  el.style.top = Math.round(top) + 'px';
}


async function openWordPop(span) {
  const raw = span.dataset.w;
  if (!raw) return;
  const el = ensureWordPop();

  // 同一个词再点一次就收起来
  if (POP.at === span && !el.hidden) { closeWordPop(); return; }

  POP.at = span;
  POP.seq += 1;
  const my = POP.seq;

  el.hidden = false;
  el.innerHTML = '<div class="wp-load">查 ' + esc(raw) + '…</div>';
  placeWordPop(el, span);                       // 先摆好再填内容，免得跳一下

  let r;
  try {
    r = await api('GET', '/api/word/mini?w=' + encodeURIComponent(raw));
  } catch (e) {
    closeWordPop();
    return;
  }
  if (my !== POP.seq || POP.at !== span) return;   // 已经点了别的词
  if (!r || !r.ok) { closeWordPop(); return; }     // 虚词、查不到的就别弹

  // 直接显示**原型**：例句里是 lurking，框里就写 lurk —— 查的就是它，
  // 顶上加个「lurking」反而让人以为要查那个变形。
  el.innerHTML =
    '<div class="wp-head">' +
      '<b class="wp-word">' + esc(r.en || raw) + '</b>' +
      (r.ph ? '<span class="wp-ph">' + esc(r.ph) + '</span>' : '') +
      '<button class="wp-spk" title="朗读">🔊</button>' +
    '</div>' +
    '<div class="wp-cn">' + esc(r.cn) + '</div>' +
    '<div class="wp-act">' +
      '<button class="wp-more">更多</button>' +
      (r.in_library
        ? '<span class="wp-inlib">已在词库</span>'
        : '<button class="wp-add">＋ 加入词库</button>') +
    '</div>';
  placeWordPop(el, span);                       // 内容填完高度变了，重摆一次

  const spk = el.querySelector('.wp-spk');
  if (spk) spk.onclick = () => speak(r.en || raw);

  const more = el.querySelector('.wp-more');
  if (more) more.onclick = () => {
    closeWordPop();
    const target = r.en || raw;
    // 已经在查词页里 → 返回目标记成"当前这个词"，这样返回键是回到上一个看过的词；
    // 从别的页面点过来的 → 返回那个页面。
    const from = (S.view === 'look' && lookWord)
      ? { type: 'word', word: lookWord }
      : { type: 'view', view: S.view };
    openLook(target, from);
  };

  const add = el.querySelector('.wp-add');
  if (add) add.onclick = async () => {
    add.disabled = true;
    add.textContent = '加入中…';
    try {
      await api('POST', '/api/words', { en: r.en || raw, cn: r.cn, pos: r.pos || '', ph: r.ph || '' });
      add.outerHTML = '<span class="wp-inlib">已加入词库</span>';
      toast('已加入词库', 'ok');
      // 三处计数都要刷：顶栏、词库下拉里的「名字（N）」、词库页的「共 N 个词」。
      // 只调 loadWords 是不够的 —— 它只管单词列表，下拉和顶栏都不会动（kk 报的计数不变）。
      if (typeof loadWords === 'function') loadWords();
      if (typeof refreshBookSelects === 'function') refreshBookSelects();
      if (typeof loadStats === 'function') loadStats();
    } catch (e) {
      add.disabled = false;
      add.textContent = '＋ 加入词库';
      toast('加入失败：' + e.message, 'bad');
    }
  };
}


/* ---------------- 绑定 ---------------- */

function bindWordPop() {
  // 例句容器里点词 → 弹框（事件委托，例句是动态生成的）
  document.addEventListener('click', (e) => {
    const span = e.target.closest('.wd[data-w]');
    if (span) {
      e.preventDefault();
      e.stopPropagation();
      openWordPop(span);
      return;
    }
    // 点框里面不算"点别处"
    if (e.target.closest('#wordPop')) return;
    closeWordPop();
  });

  // 滚动、改窗口大小、切页面都收起来
  window.addEventListener('scroll', closeWordPop, { passive: true });
  window.addEventListener('resize', closeWordPop);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeWordPop(); });
}
