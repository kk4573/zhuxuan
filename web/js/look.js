/* 竹喧 · 查词
 * 查一个词的完整资料：音标、释义、例句、短语、同义词、词形变化，
 * 以及折叠在「更多」里的柯林斯 / 英英 / 词源 / 报刊例句 / 影视例句 / 网络释义。
 * 查过一次会缓存在本机（后端 dict_full 表），之后秒回。
 */

let lookWord = '';          // 当前显示的是哪个词（加词、朗读要用）

async function doLookup(word, force) {
  const w = (word || '').trim();
  const box = $('#lookResult');
  if (!w) return;

  lookWord = w;
  $('#lookHint').hidden = true;
  box.innerHTML = '<div class="lookwait">正在查 ' + esc(w) + ' …</div>';

  let r;
  try {
    r = await api('POST', '/api/lookup/full', { en: w, force: !!force });
  } catch (e) {
    box.innerHTML = '<div class="lookwait bad">查询失败：' + esc(e.message) + '</div>';
    return;
  }
  if (!r || !r.ok) {
    box.innerHTML =
      '<div class="lookwait">' +
      '词典里没有 <b>' + esc(w) + '</b>' +
      (r && r.reason ? '<span class="dim">（' + esc(r.reason) + '）</span>' : '') +
      '</div>';
    return;
  }
  if (lookWord !== w) return;             // 已经查了别的词，丢弃这次结果
  renderLook(r);
}

/* ---------------- 各个小块的渲染 ---------------- */

function lookPh(r) {
  const us = r.ph_us || r.ph || '';
  const uk = r.ph_uk || '';
  if (!us && !uk) return '';
  // 英美发音相同时只写一个，避免「英/美 /…/」这种斜杠套斜杠的写法
  const body = (us && uk && us === uk)
    ? '<span>/' + esc(us) + '/</span><em>英美同</em>'
    : (us ? '<span>美 /' + esc(us) + '/</span>' : '') +
      (uk ? '<span>英 /' + esc(uk) + '/</span>' : '');
  return '<div class="lookph">' + body + '</div>';
}

// 把例句里的目标词标出来，一眼能找到
function highlight(text, word) {
  const safe = esc(text);
  if (!word) return safe;
  const core = word.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  if (!core) return safe;
  return safe.replace(new RegExp('\\b(' + core + '\\w{0,3})\\b', 'gi'), '<b class="hl">$1</b>');
}

function lookTags(r) {
  const all = (r.exam || []).filter(Boolean);
  if (!all.length) return '';
  const show = all.slice(0, 5);                  // 太多会跟单词抢地方
  const rest = all.length - show.length;
  return '<div class="looktags">' +
    show.map((t) => '<span>' + esc(t) + '</span>').join('') +
    (rest > 0 ? '<span class="more-tag" title="' + esc(all.join('、')) + '">+' + rest + '</span>' : '') +
    '</div>';
}

function lookSents(r) {
  if (!r.sents || !r.sents.length) return '';
  const items = r.sents.map((s) =>
    '<div class="sent">' +
      '<div class="sent-en">' + tokenizeSentence(s.en, r.en) + '</div>' +
      (s.cn ? '<div class="sent-cn">' + esc(s.cn) + '</div>' : '') +
      (s.src ? '<div class="sent-src">' + esc(s.src) + '</div>' : '') +
    '</div>').join('');
  return '<div class="looksec"><h5>例句</h5>' + items + '</div>';
}

function lookPhrs(r) {
  if (!r.phrs || !r.phrs.length) return '';
  return '<div class="looksec"><h5>短语搭配</h5><div class="lookphrs">' +
    r.phrs.map((p) => '<div><b>' + esc(p.en) + '</b><span>' + esc(p.cn) + '</span></div>').join('') +
    '</div></div>';
}

function lookSynos(r) {
  if (!r.synos || !r.synos.length) return '';
  return '<div class="looksec"><h5>同义词</h5>' +
    r.synos.map((s) =>
      '<div class="syno">' +
        (s.pos ? '<em>' + esc(s.pos) + '</em>' : '') +
        '<span class="syno-w">' + (s.words || []).map((w) => esc(w)).join('、') + '</span>' +
        (s.cn ? '<span class="dim">' + esc(s.cn) + '</span>' : '') +
      '</div>').join('') + '</div>';
}

function lookForms(r) {
  if (!r.forms || !r.forms.length) return '';
  return '<div class="looksec"><h5>词形变化</h5><div class="lookforms">' +
    r.forms.map((f) =>
      '<div>' + (f.pos ? '<em>' + esc(f.pos) + '</em>' : '') +
      '<b>' + esc(f.en) + '</b>' + (f.cn ? '<span class="dim">' + esc(f.cn) + '</span>' : '') +
      '</div>').join('') + '</div></div>';
}

/* 「更多」——折叠起来的一大块 */
function lookMore(r) {
  const m = r.more || {};
  const parts = [];

  if (m.collins && m.collins.length) {
    parts.push('<h6>柯林斯词典释义</h6>' +
      m.collins.map((c) =>
        '<div class="col">' +
          '<div class="col-head">' +
            (c.star ? '<span class="star">' + '★'.repeat(Math.min(5, parseInt(c.star, 10) || 0)) + '</span>' : '') +
            (c.pos ? '<em>' + esc(c.pos) + (c.pos_cn ? ' ' + esc(c.pos_cn) : '') + '</em>' : '') +
          '</div>' +
          '<div class="col-tran">' + esc(c.tran) + '</div>' +
          (c.sent ? '<div class="sent"><div class="sent-en">' + esc(c.sent.en) + '</div>' +
                    '<div class="sent-cn">' + esc(c.sent.cn) + '</div></div>' : '') +
        '</div>').join(''));
  }

  if (m.ee && m.ee.length) {
    parts.push('<h6>英英释义（WordNet）</h6>' +
      m.ee.map((e) =>
        '<div class="ee">' +
          (e.pos ? '<em>' + esc(e.pos) + '</em> ' : '') + esc(e.tran) +
          ((e.examples || []).length
            ? '<div class="ee-ex">' + e.examples.map((x) => '· ' + esc(x)).join('<br>') + '</div>' : '') +
          ((e.similar || []).length
            ? '<div class="dim">近义：' + e.similar.map((x) => esc(x)).join('、') + '</div>' : '') +
        '</div>').join(''));
  }

  if (m.etym && m.etym.length) {
    parts.push('<h6>词源</h6>' +
      m.etym.map((e) =>
        '<div class="etym">' + esc(e.text) +
        (e.src ? '<span class="dim">　——' + esc(e.src) + '</span>' : '') + '</div>').join(''));
  }

  if (m.auth && m.auth.length) {
    parts.push('<h6>报刊例句</h6>' +
      m.auth.map((s) =>
        '<div class="sent"><div class="sent-en">' + tokenizeSentence(s.en, '') + '</div>' +
        (s.src ? '<div class="sent-src">' + esc(s.src) + '</div>' : '') + '</div>').join(''));
  }

  if (m.media && m.media.length) {
    parts.push('<h6>影视例句</h6>' +
      m.media.map((s) =>
        '<div class="sent"><div class="sent-en">' + esc(s.en) + '</div>' +
        (s.cn ? '<div class="sent-cn">' + esc(s.cn) + '</div>' : '') + '</div>').join(''));
  }

  if (m.web && m.web.length) {
    parts.push('<h6>网络释义</h6><div class="lookphrs">' +
      m.web.map((w) => '<div><b>' + esc(w.cn) + '</b>' +
        (w.support ? '<span class="dim">' + esc(String(w.support)) + ' 次引用</span>' : '') +
        '</div>').join('') + '</div>');
  }

  if (!parts.length) return '';
  return '<details class="lookmore"><summary>更多</summary>' +
    '<div class="morebody">' + parts.join('') + '</div></details>';
}

/* ---------------- 整页渲染 ---------------- */

function renderLook(r) {
  const lib = r.in_library
    ? '<span class="inlib">已在词库　掌握度 ' + (r.mastery === null ? '—' : r.mastery) + '</span>'
    : '<button class="link" id="lookAddBtn">＋ 加入词库</button>';

  $('#lookResult').innerHTML =
    '<div class="lookcard">' +
      '<div class="looktop">' +
        '<div class="looktitle">' +
          '<h2>' + esc(r.en) +
            '<button class="spk" id="lookSpk" title="朗读">🔊</button>' +
          '</h2>' +
          lookPh(r) +
        '</div>' +
        '<div class="lookside">' + lookTags(r) + lib + '</div>' +
      '</div>' +
      '<div class="looksec"><h5>释义</h5><div class="lookcn">' + esc(r.cn) + '</div></div>' +
      lookSents(r) + lookPhrs(r) + lookSynos(r) + lookForms(r) +
      lookMore(r) +
      '<div class="lookfoot">来源：' + esc(r.source || '有道词典') +
        '<button class="link" id="lookRefresh">重新查</button></div>' +
    '</div>';

  const spk = $('#lookSpk');
  if (spk) spk.onclick = () => speak(r.en || lookWord);
  const rf = $('#lookRefresh');
  if (rf) rf.onclick = () => doLookup(lookWord, true);

  const add = $('#lookAddBtn');
  if (add) add.onclick = async () => {
    add.disabled = true;
    add.textContent = '加入中…';
    try {
      const bsel = $('#lookBook');
      const bid = bsel && bsel.value ? parseInt(bsel.value, 10) : undefined;
      const res = await api('POST', '/api/words', { en: r.en, cn: r.cn, pos: r.pos, ph: r.ph, book_id: bid });
      toast(res && res.existing ? '已在词库中，已加进当前词库：' + r.en : '已加入词库：' + r.en, 'ok');
      doLookup(r.en);              // 重新渲染，这回会显示「已在词库」
      refreshAfterWordChange();
    } catch (e) {
      add.disabled = false;
      add.textContent = '＋ 加入词库';
      toast('加入失败：' + e.message, 'bad');
    }
  };
}


/* ==================== 查词页的元素绑定 ==================== */

/** 把某个词填进查词框（例句里点「更多」跳过来时用）。 */
function setLookInput(w) {
  const inp = $('#lookInput');
  if (!inp) return;
  inp.value = w || '';
  const cl = $('#lookClear');
  if (cl) cl.hidden = !inp.value;
}


/**
 * 进入查词页看一个词。**所有跳转都走这里**，因为它要记录"从哪来的"。
 *
 * `from` 是"跳进来之前所处的状态"，会被**压进返回栈**：
 *   { type: 'word', word: 'abandon' }   ← 原来在看 abandon 这个词
 *   { type: 'view', view: 'lib' }       ← 原来在词库页
 *
 * 用栈而不是单个值 —— 否则「词库 → 词A → 词B」这种嵌套，从 B 退回 A 之后就没法再退回词库了
 * （用户反馈的就是这个）。传 null 表示自己在查词框敲的查询，不算跳转，栈清空、不显示返回键。
 */
async function openLook(word, from) {
  if (S.view !== 'look') showView('look');
  if (from) S.lookStack.push(from);
  else S.lookStack = [];
  renderLookBack();
  await fillLookInput(word);
}


/** 只把查词框填上并查询，**不动返回栈**（返回时就用它，免得把退回去的路又压回去）。 */
async function fillLookInput(word) {
  const inp = $('#lookInput');
  if (inp) inp.value = word || '';
  const cl = $('#lookClear');
  if (cl) cl.hidden = !inp || !inp.value;
  await doLookup(word);
}


/** 查词页左上角那个「← 返回」：栈里还有东西才出现。 */
function renderLookBack() {
  const btn = $('#lookBack');
  if (!btn) return;
  if (!S.lookStack.length) { btn.hidden = true; return; }
  btn.hidden = false;
  btn.textContent = '← 返回';
  btn.onclick = () => {
    const back = S.lookStack.pop();
    if (!back) { renderLookBack(); return; }
    if (back.type === 'word') {
      fillLookInput(back.word);        // 回到上一个看过的词；栈里可能还有更早的一层
    } else {
      S.lookStack = [];                // 回到某个页面，这趟跳转就算结束了
      showView(back.view);
    }
    renderLookBack();
  };
}


function bindLook() {
  renderLookBack();
  const inp = $('#lookInput');
  const syncClear = () => { $('#lookClear').hidden = !inp.value; };

  const run = () => {
    const w = inp.value.trim();
    // 自己敲的查询不算"跳转"，所以不给返回键
    if (w) openLook(w, null);
  };

  $('#lookBtn').onclick = run;
  inp.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); run(); return; }
    if (e.key === 'Escape' && inp.value) { e.preventDefault(); inp.value = ''; syncClear(); }
  });
  inp.oninput = syncClear;
  $('#lookClear').onclick = () => {
    inp.value = '';
    syncClear();
    inp.focus();
    $('#lookResult').innerHTML = '';
    $('#lookHint').hidden = false;
  };
}
