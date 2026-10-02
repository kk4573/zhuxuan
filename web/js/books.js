/* 竹喧 · 词库（多个）
 *
 * 一个单词可以同时属于多个词库，掌握度是跟着**单词**走的，所以天然共享。
 * 抽词时只从选中的那一个词库抽，不做跨库混合。
 */

let BOOKS = [];              // 词库列表（后端给的，带 count）
let VOCABS = [];             // 内置词表清单

const DEFAULT_BOOK_NAME = '我的词库';   // 兜底用，正常以后端返回的 is_default 为准


/* ---------------- 取数据 ---------------- */

async function loadBooks(force) {
  if (BOOKS.length && !force) return BOOKS;
  try {
    const r = await api('GET', '/api/books');
    BOOKS = r.items || [];
  } catch (e) {
    BOOKS = [];
  }
  return BOOKS;
}

function bookById(id) {
  return BOOKS.find((b) => b.id === id) || null;
}

function defaultBookId() {
  const d = BOOKS.find((b) => b.is_default);
  return d ? d.id : (BOOKS[0] ? BOOKS[0].id : null);
}

/** 当前背诵用的词库（下拉里选的，选了就用；没选过就用默认词库） */
function curStudyBook() {
  const sel = $('#studyBook');
  const id = sel && sel.value ? parseInt(sel.value, 10) : null;
  return bookById(id) || bookById(defaultBookId());
}

/** 导入弹层里选的词库（不选就用默认词库） */
function curImportBookId() {
  const sel = $('#importBook');
  if (sel && sel.value) return parseInt(sel.value, 10) || null;
  return defaultBookId();
}

/** 词库页正在筛选的词库（空值 = 全部词） */
function curLibBookId() {
  const sel = $('#libBook');
  if (!sel || !sel.value) return null;
  return parseInt(sel.value, 10) || null;
}


/* ---------------- 下拉填充 ---------------- */

function fillBooks(sel, opts) {
  if (!sel) return;
  const o = opts || {};
  const keep = o.value !== undefined ? o.value : sel.value;
  let html = '';
  if (o.allOption) html += '<option value="">' + esc(o.allOption) + '</option>';
  html += BOOKS.map((b) =>
    '<option value="' + b.id + '">' + esc(b.name) + '（' + b.count + '）</option>').join('');
  sel.innerHTML = html;
  // 尽量保持原来的选择
  if (keep && bookById(parseInt(keep, 10))) sel.value = keep;
  else if (!o.allOption && !sel.value) sel.value = defaultBookId();
}

async function refreshBookSelects() {
  await loadBooks(true);
  fillBooks($('#studyBook'));
  // 词库页：进来时默认落在**默认词库**上（kk 的要求），"全部单词"仍然可以手动选
  const libCur = $('#libBook') && $('#libBook').value;
  fillBooks($('#libBook'), { allOption: '全部单词', value: libCur || defaultBookId() });
  fillBooks($('#importBook'));
  fillBooks($('#addBook'));
  fillBooks($('#lookBook'));
}


/* ---------------- 新建 / 改名 / 删除 / 设为默认 ---------------- */

function openNewBook() {
  $('#newBookName').value = '';
  msg('#newBookMsg', '');
  $('#newBookModal').hidden = false;
  setTimeout(() => $('#newBookName').focus(), 0);
}

async function createBook() {
  const name = $('#newBookName').value.trim();
  if (!name) { msg('#newBookMsg', '名字不能为空', 'bad'); return; }
  try {
    const r = await api('POST', '/api/books', { name: name });
    BOOKS = r.items || [];
    $('#newBookModal').hidden = true;
    toast('已新建词库：' + name, 'ok');
    await refreshBookSelects();
    // 新词库自动选中，方便马上往里加词
    if ($('#studyBook')) $('#studyBook').value = r.id;
    if ($('#libBook')) $('#libBook').value = r.id;
    if ($('#view-lib') && !$('#view-lib').hidden) loadWords(1);
  } catch (e) {
    msg('#newBookMsg', e.message, 'bad');
  }
}


/* ---------------- 词库管理弹层 ---------------- */

async function openBookManage() {
  await refreshBookSelects();
  renderBookList();
  msg('#bookMsg', '');
  $('#bookModal').hidden = false;
}

function renderBookList() {
  const box = $('#bookList');
  if (!box) return;
  box.innerHTML = BOOKS.map((b) =>
    '<div class="bookrow" data-id="' + b.id + '">' +
      '<div class="bookname">' + esc(b.name) +
        (b.is_default ? '<span class="bdft">默认</span>' : '') +
        (b.builtin ? '<span class="bbuiltin">' + esc(b.builtin) + '</span>' : '') +
        '<span class="dim">' + b.count + ' 个词</span>' +
      '</div>' +
      '<div class="bookops">' +
        '<button class="link" data-op="rename">改名</button>' +
        (b.is_default ? '' : '<button class="link" data-op="default">设为默认</button>') +
        (b.is_default ? '' : '<button class="link danger" data-op="del">删除</button>') +
      '</div>' +
    '</div>').join('');
}

async function bookOp(id, op) {
  const b = bookById(id);
  if (!b) return;

  if (op === 'rename') {
    const name = prompt('把「' + b.name + '」改名为：', b.name);
    if (name === null) return;
    const trimmed = name.trim();
    if (!trimmed || trimmed === b.name) return;
    try {
      const r = await api('PUT', '/api/books/' + id, { name: trimmed });
      BOOKS = r.items || [];
      toast('已改名', 'ok');
    } catch (e) { msg('#bookMsg', e.message, 'bad'); return; }
  } else if (op === 'default') {
    try {
      const r = await api('POST', '/api/books/' + id + '/default');
      BOOKS = r.items || [];
      toast('默认词库已设为「' + b.name + '」', 'ok');
    } catch (e) { msg('#bookMsg', e.message, 'bad'); return; }
  } else if (op === 'del') {
    const yes = await askConfirm('删除词库',
      '将删除词库「' + b.name + '」。\n里面的 ' + b.count + ' 个单词**本身不会被删除**，' +
      '只是不再属于这个词库（如果它们还属于别的词库，那边不受影响）。', '删除');
    if (!yes) return;
    try {
      const r = await api('DELETE', '/api/books/' + id);
      BOOKS = r.items || [];
      toast('已删除词库，清掉 ' + r.removed + ' 条归属', 'ok');
    } catch (e) { msg('#bookMsg', e.message, 'bad'); return; }
  }

  renderBookList();
  await refreshBookSelects();
  if ($('#view-lib') && !$('#view-lib').hidden) loadWords();
  loadStats();
}


/* ---------------- 内置词表 ---------------- */

async function loadVocabs() {
  if (VOCABS.length) return VOCABS;
  try {
    const r = await api('GET', '/api/vocab');
    VOCABS = r.items || [];
  } catch (e) {
    VOCABS = [];
  }
  return VOCABS;
}

async function renderVocabList() {
  await loadVocabs();
  const sel = $('#vocabSel');
  const btn = $('#vocabImport');
  const note = $('#vocabNote');
  if (!sel) return;
  if (!VOCABS.length) {
    sel.innerHTML = '<option>读不到词表清单</option>';
    if (btn) btn.disabled = true;
    return;
  }
  const keep = sel.value;
  sel.innerHTML = VOCABS.map((v) =>
    '<option value="' + esc(v.key) + '">' +
      esc(v.name) + '（约 ' + v.expect + ' 词' + (v.cached ? '，已缓存' : '') + '）' +
    '</option>').join('');
  if (keep && VOCABS.some((v) => v.key === keep)) sel.value = keep;
  if (btn) btn.disabled = false;

  // 下面那行小字跟着下拉走，免得多占一行
  const cur = VOCABS.find((v) => v.key === sel.value);
  if (note && cur) {
    note.textContent = cur.cached
      ? '词表已在本机，导入时不联网。已在词库的词不重复添加。'
      : '首次导入需联网下载词表。已在词库的词不重复添加。';
  }
}

async function importVocab(key, btn) {
  const v = VOCABS.find((x) => x.key === key);
  if (!v) return;
  const targetSel = $('#importBook');
  const targetId = targetSel && targetSel.value ? parseInt(targetSel.value, 10) : null;
  const target = bookById(targetId);

  const yes = await askConfirm('导入词表',
    '把「' + v.name + '」（约 ' + v.expect + ' 词）导入' +
    (target ? '词库「' + target.name + '」' : '一个新词库') + '？\n' +
    '首次导入需联网下载词表，之后走本机缓存。\n' +
    '已在词库的词不重复添加，掌握度和记录都保留。', '导入');
  if (!yes) return;

  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = '导入中…';
  msg('#importMsg', '正在处理「' + v.name + '」…');
  try {
    const r = await api('POST', '/api/vocab/import', {
      key: key, as_book: !targetId, book_id: targetId || undefined,
    });
    msg('#importMsg',
        '「' + r.book_name + '」导入完成：新增 ' + r.added + ' 个词，' +
        '另有 ' + Math.max(0, r.attached - r.added) + ' 个已经在库里（只加了归属）', 'ok');
    toast('已导入 ' + v.name, 'ok');
    await refreshBookSelects();
    await renderVocabList();
    if (targetSel && r.book_id) targetSel.value = r.book_id;
  } catch (e) {
    msg('#importMsg', '导入失败：' + e.message, 'bad');
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}


/* ==================== 词库相关的绑定 ==================== */

function bindBooks() {
  $('#newBookBtn').onclick = openNewBook;
  $('#newBookCancel').onclick = () => { $('#newBookModal').hidden = true; };
  $('#newBookOk').onclick = createBook;
  $('#newBookName').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); createBook(); }
  });

  $('#bookClose').onclick = () => { $('#bookModal').hidden = true; };

  // 词库管理列表里的操作（内容是动态生成的，用事件委托）
  $('#bookList').addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-op]');
    if (!btn) return;
    const row = btn.closest('.bookrow');
    if (!row) return;
    bookOp(parseInt(row.dataset.id, 10), btn.dataset.op);
  });

  // 点名字也能进管理（词库页那个「＋ 词库」旁边的入口由各自按钮负责）
  $('#libBook').onchange = () => { currentPage = 1; loadWords(1, true); };
  $('#studyBook').onchange = () => { renderReadyHint(); };

  // 词库管理（改名 / 设为默认 / 删除）——以前没有入口，kk 找不到删除键
  $('#bookManageBtn').onclick = openBookManage;

  // 内置词表：下拉选一个，再点右边的导入
  $('#vocabImport').onclick = () => {
    const key = $('#vocabSel').value;
    if (key) importVocab(key, $('#vocabImport'));
  };
  $('#vocabSel').onchange = () => renderVocabList();

  // 打开导入弹层时刷新词表清单
  const origImport = $('#importBtn').onclick;
  $('#importBtn').onclick = async (ev) => {
    await refreshBookSelects();
    await renderVocabList();
    if (origImport) origImport.call($('#importBtn'), ev);
  };
}
