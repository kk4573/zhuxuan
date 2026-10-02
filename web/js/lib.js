/* 竹喧 · 词库页
 * 列表与分页、搜索排序、增删改、批量导入、释义补全。
 */

/* ==================== 词库 ==================== */

// 循环调用后端补全缺释义的词，onTick 用来显示进度
async function runEnrich(onTick) {
  let total = 0;
  let failed = [];
  for (let i = 0; i < 400; i++) {
    let r;
    try { r = await api('POST', '/api/words/enrich?limit=30'); }
    catch (e) { break; }
    total += r.filled;
    failed = failed.concat(r.failed || []);
    if (onTick) onTick(total);
    if (!r.done || r.remain === 0) break;
  }
  return { total: total, failed: failed };
}

const PAGE_SIZE = 100;
let currentPage = 1;

async function loadWords(page, scrollTop) {
  if (page) currentPage = page;
  const q = $('#search').value.trim();
  const sort = $('#sort').value;
  try {
    const bid = curLibBookId();
    const r = await api('GET', '/api/words?q=' + encodeURIComponent(q) +
                        '&sort=' + sort + '&page=' + currentPage + '&size=' + PAGE_SIZE +
                        (bid ? '&book_id=' + bid : ''));
    // 删掉当前页最后一条后，这一页可能空了 —— 往前退一页
    if (!r.items.length && r.total > 0 && currentPage > 1) {
      currentPage -= 1;
      return loadWords(currentPage, scrollTop);
    }
    renderWords(r);
    // 翻页 / 搜索 / 换排序之后回到**页面最顶部**，连搜索栏和工具栏一起看见。
    // （之前滚到 .listwrap 顶部，反倒把工具栏推出视野了）
    if (scrollTop) window.scrollTo({ top: 0, behavior: 'smooth' });
  } catch (e) {
    toast('读取词库失败：' + e.message, 'bad');
  }
}

function mastBar(m) {
  const pct = Math.min(100, (m || 0) / 10 * 100);
  const cls = m >= 10 ? 'lv4' : (m >= 5 ? 'lv3' : (m >= 2 ? 'lv2' : 'lv1'));
  return '<span class="mbar"><i class="' + cls + '" style="width:' + pct + '%"></i></span>' +
         '<span class="mnum">' + (m || 0) + (m >= 10 ? ' 精通' : '') + '</span>';
}

function renderWords(r) {
  const tb = $('#wordBody');
  wordCache = {};
  r.items.forEach((w) => { wordCache[w.id] = w; });

  if (!r.items.length) {
    tb.innerHTML = '';
    $('#libEmpty').hidden = false;
    $('#libEmpty').textContent = $('#search').value.trim()
      ? '未找到匹配的单词'
      : '词库还是空的，点「导入」把单词放进来';
  } else {
    $('#libEmpty').hidden = true;
    tb.innerHTML = r.items.map((w) =>
      '<tr data-id="' + w.id + '">' +
        '<td class="en">' + esc(w.en) + '</td>' +
        '<td class="cn' + (w.cn ? '' : ' miss') + '">' + (w.cn ? esc(w.cn) : '（缺释义）') + '</td>' +
        '<td class="mast">' + mastBar(w.mastery) + '</td>' +
        '<td class="cnt">' + w.right_cnt + ' / ' + w.wrong_cnt + '</td>' +
        '<td class="ops"><button class="link" data-act="edit">改</button>' +
        '<button class="link danger" data-act="del">删</button></td>' +
      '</tr>').join('');
  }
  renderPager($('#listHead'), r, true);     // 上方那条带「直达底部」
  renderPager($('#listFoot'), r, false);
}

// 列表上方和下方各放一条同样的翻页条 —— 省得每次翻页都要滑到最底下
function renderPager(el, r, withJumpBottom) {
  if (!el) return;
  const size = r.size || PAGE_SIZE;
  if (r.total <= size) {
    el.innerHTML = '<span>共 ' + r.total + ' 个词</span>';
    return;
  }
  const pages = Math.max(1, Math.ceil(r.total / size));
  const from = (r.page - 1) * size + 1;
  const to = Math.min(r.total, r.page * size);
  const jump = withJumpBottom ? '<button class="link" data-page="bottom">↓ 直达底部</button>' : '';
  el.innerHTML =
    '<span>共 ' + r.total + ' 个词　·　第 ' + from + '–' + to + ' 个</span>' +
    '<span class="pager">' + jump +
      '<button class="link" data-page="prev"' + (r.page <= 1 ? ' disabled' : '') + '>← 上一页</button>' +
      '<span class="pageno">第 ' + r.page + ' / ' + pages + ' 页</span>' +
      '<button class="link" data-page="next"' + (r.page >= pages ? ' disabled' : '') + '>下一页 →</button>' +
    '</span>';
}

async function openEdit(id) {
  await refreshBookSelects();          // 词库下拉要最新
  const bookSel = $('#addBook');
  const bookRow = $('#editBookRow');
  if (bookRow) bookRow.hidden = !!id;  // 改词时不改归属
  if (!id && bookSel && [...BOOKS].some((b) => b.id === curLibBookId())) {
    bookSel.value = curLibBookId() || defaultBookId();
  }
  editingId = id || null;
  const w = id ? wordCache[id] : null;
  $('#editTitle').textContent = id ? '修改单词' : '添加单词';
  $('#editEn').value = w ? w.en : '';
  $('#editCn').value = w ? w.cn : '';
  $('#editPos').value = w ? w.pos : '';
  $('#editPh').value = w ? w.ph : '';
  msg('#editMsg', '');
  autoFilled.cn = autoFilled.pos = autoFilled.ph = false;   // 重置自动填充标记
  $('#editModal').hidden = false;
  setTimeout(() => $('#editEn').focus(), 0);
}

// ==================== 答错后的「跟着打一遍」 ====================

function hideRetype() {
  $('#retypeWrap').hidden = true;
  $('#retypeInput').value = '';
  $('#retypeInput').className = '';
  $('#retypeMsg').textContent = '';
  $('#retypeMsg').className = 'retypemsg';
}

function showRetype() {
  const inp = $('#retypeInput');
  inp.value = '';
  inp.className = '';
  $('#retypeMsg').textContent = '';
  $('#retypeMsg').className = 'retypemsg';
  $('#retypeWrap').hidden = false;
  setTimeout(() => inp.focus(), 0);
}

async function checkRetype() {
  const q = S.queue[S.idx];
  const inp = $('#retypeInput');
  const typed = inp.value.trim();
  if (!q || !typed) return;
  const box = $('#retypeMsg');
  let r;
  try {
    // 判定仍然走后端（规则只有一份），但这个接口不记分、不动掌握度
    r = await api('POST', '/api/judge', { answer: q.en, typed: typed });
  } catch (e) {
    box.textContent = '判定失败：' + e.message;
    box.className = 'retypemsg bad';
    return;
  }
  if (r.correct) {
    inp.className = 'ok';
    box.textContent = '✓ 打对了' + (r.diff === null && typed.length === q.en.length ? '' : '') +
                      '　可以再打一遍，或按空格继续';
    box.className = 'retypemsg ok';
    inp.value = '';
    speak(q.en);
  } else {
    inp.className = 'bad';
    box.textContent = '✗ 还不对，对照上面的正确答案再来一遍';
    box.className = 'retypemsg bad';
    inp.select();
  }
}

// 每个字段当前的值是不是「自动查来的」（用户手改过就变 false）
const autoFilled = { cn: false, pos: false, ph: false };

// ==================== 查看上一个 ====================

let prevCursor = -1;

function renderPrev(i) {
  const q = S.queue[i];
  if (!q) return false;
  const r = q.result;
  let html = '<div class="prevcn">' + esc(q.cn || '（无释义）') + '</div>';
  html += '<div class="row"><span class="lab">答案</span><span class="ans">' + esc(q.en) + '</span>' +
          (q.ph ? '<span class="ph">' + esc(q.ph) + '</span>' : '') + '</div>';
  if (r) {
    html += '<div class="row"><span class="lab">你填的</span><span class="' +
            (r.correct ? 'ans' : 'mine') + '">' + esc(r.typed || '（跳过）') + '</span></div>';
    html += '<div class="row"><span class="lab">结果</span><span class="' +
            (r.correct ? 'ok-t' : 'bad-t') + '">' + (r.correct ? '答对' : '答错') + '</span>' +
            '<span class="ph">掌握度 ' + r.from + ' → ' + r.mastery +
            (r.retried && r.correct ? '（重考答对，不计分）' : '') + '</span></div>';
  } else {
    html += '<div class="dim">这一题还没有作答记录</div>';
  }
  $('#prevBody').innerHTML = html;
  $('#prevCursor').textContent = '第 ' + (i + 1) + ' / ' + S.queue.length + ' 题';
  $('#prevOlder').disabled = i <= 0;
  return true;
}

function openPrev() {
  if (S.idx <= 0) { toast('这已经是第一题了'); return; }
  prevCursor = S.idx - 1;
  renderPrev(prevCursor);
  $('#prevModal').hidden = false;
}

function closePrev() {
  $('#prevModal').hidden = true;
  setTimeout(() => $('#qInput').focus(), 0);
}

// ==================== 设置 ====================


/* ==================== 词库页的元素绑定 ==================== */

function bindLib() {

  // 工具条 + 加词弹层的自动填充
  // 词库工具条
  const searchInput = $('#search');
  const syncClear = () => { $('#searchClear').hidden = !searchInput.value; };

  searchInput.oninput = () => {
    currentPage = 1;
    syncClear();
    clearTimeout(window.__searchTimer);
    window.__searchTimer = setTimeout(() => loadWords(currentPage, true), 220);
  };
  searchInput.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || !searchInput.value) return;
    e.preventDefault();
    searchInput.value = '';
    syncClear();
    currentPage = 1;
    loadWords(currentPage, true);
  });
  $('#searchClear').onclick = () => {
    searchInput.value = '';
    syncClear();
    currentPage = 1;
    loadWords(currentPage, true);
    searchInput.focus();
  };

  $('#sort').onchange = () => { currentPage = 1; loadWords(currentPage, true); };
  $('#addBtn').onclick = () => openEdit(null);

  // 手动改过某个字段 → 这个字段以后不再被自动覆盖
  [['#editCn', 'cn'], ['#editPos', 'pos'], ['#editPh', 'ph']].forEach((pair) => {
    $(pair[0]).addEventListener('input', () => { autoFilled[pair[1]] = false; });
  });

  // 输入英文后自动查词典填中文 / 词性 / 音标
  let lookupTimer = null;
  $('#editEn').addEventListener('input', () => {
    clearTimeout(lookupTimer);
    const en = $('#editEn').value.trim();
    if (!en || /[\u4e00-\u9fff]/.test(en)) return;
    lookupTimer = setTimeout(() => {
      msg('#editMsg', '正在查词典…');
      api('POST', '/api/lookup', { en: en }).then((r) => {
        // 这期间单词又被改过了 → 丢弃这次结果，等下一次查询
        if ($('#editEn').value.trim() !== en) return;
        if (r.ok) {
          const fill = (sel, key, val) => {
            if (shouldFill(autoFilled, key, $(sel).value)) {
              $(sel).value = val;
              autoFilled[key] = true;
            }
          };
          fill('#editCn', 'cn', r.cn);
          fill('#editPos', 'pos', r.pos || '');
          fill('#editPh', 'ph', r.ph || '');
          msg('#editMsg', '（来自' + r.source + '）', 'ok');
        } else {
          msg('#editMsg', r.reason || '查不到这个词，手动填一下', '');
        }
      }).catch((e) => msg('#editMsg', e.message, 'bad'));
    }, 550);
  });

  // 补全释义 + 翻页条
  // 一键补齐词库里所有缺释义的词
  $('#enrichBtn').onclick = async () => {
    const btn = $('#enrichBtn');
    btn.disabled = true;
    const r = await runEnrich((t) => { btn.textContent = '补全中… ' + t; });
    btn.disabled = false;
    toast('已补全 ' + r.total + ' 个' +
          (r.failed.length ? '，' + r.failed.length + ' 个词典里查不到' : ''), 'ok');
    loadWords(); loadStats();
  };

  ['listHead', 'listFoot'].forEach((id) => {
    $('#' + id).addEventListener('click', (e) => {
      const dir = e.target.dataset && e.target.dataset.page;
      if (dir === 'prev' && currentPage > 1) loadWords(currentPage - 1, true);
      else if (dir === 'next') loadWords(currentPage + 1, true);
      else if (dir === 'bottom') window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
    });
  });

  // 表格里的 改 / 删
  $('#wordBody').addEventListener('click', async (e) => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const id = parseInt(btn.closest('tr').dataset.id, 10);
    if (btn.dataset.act === 'del') {
      const yes = await askConfirm('删除单词',
        '确定删除「' + (wordCache[id] ? wordCache[id].en : '') + '」？该单词的学习记录将一并删除。',
        '删除');
      if (!yes) return;
      try { await api('DELETE', '/api/words/' + id); toast('已删除', 'ok'); loadWords(); loadStats(); }
      catch (err) { toast(err.message, 'bad'); }
    } else {
      openEdit(id);
    }
  });

  // 添加 / 修改弹层
  $('#editCancel').onclick = () => { $('#editModal').hidden = true; };
  $('#editOk').onclick = async () => {
    const en = $('#editEn').value.trim();
    if (!en) { msg('#editMsg', '英文不能为空', 'bad'); return; }
    const body = {
      en: en,
      cn: $('#editCn').value.trim(),
      pos: $('#editPos').value.trim(),
      ph: $('#editPh').value.trim(),
    };
    // res 要在两个分支外面声明 —— 之前写在 else 块里，后面用到就 ReferenceError 了
    let res = null;
    try {
      if (editingId) {
        await api('PUT', '/api/words/' + editingId, body);
      } else {
        const bsel = $('#addBook');
        if (bsel && bsel.value) body.book_id = parseInt(bsel.value, 10);
        res = await api('POST', '/api/words', body);
      }
      if (editingId) {
        $('#editModal').hidden = true;
        toast('已保存', 'ok');
      } else if (res && res.existing) {
        msg('#editMsg', '「' + en + '」已在词库，已加进当前词库（释义没动）', 'ok');
      } else {
        $('#editModal').hidden = true;
        toast('已添加', 'ok');
      }
      loadWords(); loadStats();
    } catch (err) { msg('#editMsg', err.message, 'bad'); }
  };
  $('#editEn').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('#editOk').click(); });

  // 导入弹层
  $('#importBtn').onclick = () => {
    $('#importText').value = '';
    $('#importFile').value = '';
    const lb = $('#importFile').closest('.filebtn');
    if (lb && lb.dataset.orig) lb.textContent = lb.dataset.orig;
    msg('#importMsg', '');
    $('#importModal').hidden = false;
    setTimeout(() => $('#importText').focus(), 0);
  };
  $('#importCancel').onclick = () => { $('#importModal').hidden = true; };
  // 选了文件就把文件名显示在按钮上（还是能点「导入」提交）
  $('#importFile').onchange = () => {
    const f = $('#importFile').files[0];
    const lb = $('#importFile').closest('.filebtn');
    if (!lb) return;
    if (!lb.dataset.orig) lb.dataset.orig = lb.textContent.trim();
    lb.textContent = f ? f.name : lb.dataset.orig;
  };
  $('#importOk').onclick = async () => {
    const text = $('#importText').value;
    const file = $('#importFile').files[0];
    if (!text.trim() && !file) { msg('#importMsg', '请粘贴单词，或选一个 Excel 文件', 'bad'); return; }
    $('#importOk').disabled = true;
    msg('#importMsg', '正在导入…');
    try {
      let r;
      if (file) {
        const fd = new FormData();
        fd.append('file', file);
        if (curImportBookId()) fd.append('book_id', String(curImportBookId()));
        const res = await fetch('/api/words/import-xlsx', { method: 'POST', body: fd });
        r = await res.json();
        if (!res.ok) throw new Error(r.detail || ('HTTP ' + res.status));
      } else {
        r = await api('POST', '/api/words/auto-add', {
          text: text, lookup: false, book_id: curImportBookId(),
        });
      }
      let line = '导入完成：新增 ' + r.added + ' 个，跳过重复 ' + r.skipped + ' 个';
      msg('#importMsg', line, 'ok');
      loadWords(); loadStats();
      if (r.no_cn) {
        line += '\n正在自动查词典补全释义…';
        msg('#importMsg', line, 'ok');
        const en = await runEnrich((t) => msg('#importMsg', line + '\n已补全 ' + t + ' 个…', 'ok'));
        await loadStats();
        const left = (S.stats && S.stats.no_cn_pending) || 0;
        msg('#importMsg',
            '导入完成：新增 ' + r.added + ' 个，跳过重复 ' + r.skipped + ' 个\n' +
            (left ? '已补全 ' + en.total + ' 个释义，还有 ' + left + ' 个词典里查不到，可在词库里手动补'
                  : '释义已全部补全（' + en.total + ' 个）'), 'ok');
        loadWords();
      }
    } catch (err) {
      msg('#importMsg', err.message, 'bad');
    } finally {
      $('#importOk').disabled = false;
    }
  };
}
