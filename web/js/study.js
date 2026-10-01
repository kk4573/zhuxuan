/* 竹喧 · 背单词页
 * 出题、判定、答错跟打、查看上一个、「你写的是另一个词」、收尾小结。
 */

/* ==================== 背诵 ==================== */

async function startSession() {
  const size = Math.max(1, parseInt($('#sizeInput').value, 10) || 1);
  $('#startBtn').disabled = true;
  try {
    const r = await api('POST', '/api/session/start', {
      size: size, book_id: (curStudyBook() || {}).id,
    });
    S.sessionId = r.session_id;
    S.queue = r.items.map((w) => Object.assign({}, w, { firstTry: null }));
    S.total = r.count;
    S.idx = 0;
    S.done = new Set();
    S.asked = 0;
    S.wrongWords = [];
    S.submitted = false;
    showPhase('quiz');
    setIme(true);
    renderQuestion();
  } catch (e) {
    toast(e.message, 'bad');
  } finally {
    $('#startBtn').disabled = false;
  }
}

function renderQuestion() {
  const q = S.queue[S.idx];
  if (!q) { finishSession(false); return; }
  S.submitted = false;
  $('#qCn').textContent = q.cn || '';
  const inp = $('#qInput');
  inp.value = '';
  inp.className = '';
  inp.readOnly = false;
  $('#qSpk').classList.add('hide');
  $('#qFb').innerHTML = '';
  $('#otherWord').hidden = true;
  hideRetype();
  $('#imeWarn').hidden = true;
  updateProgress();
  inp.focus();
}

function updateProgress() {
  const got = S.done.size;
  $('#quizBar').style.width = (S.total ? (got / S.total * 100) : 0) + '%';
  $('#quizProgress').innerHTML = '已掌握 <b>' + got + '</b> / ' + S.total + ' 个';
}

async function submit(skipped) {
  if (S.submitted) return;
  const inp = $('#qInput');
  const typed = inp.value;
  if (!skipped && !typed.trim()) return;
  const q = S.queue[S.idx];
  if (!q) return;

  S.submitted = true;
  inp.readOnly = true;
  inp.blur();

  let r;
  try {
    r = await api('POST', '/api/session/answer', {
      session_id: S.sessionId, word_id: q.id, typed: typed, skipped: !!skipped,
    });
  } catch (e) {
    S.submitted = false;
    inp.readOnly = false;
    inp.focus();
    toast(e.message, 'bad');
    return;
  }

  recordAnswer(q, r, typed);
  $('#qSpk').classList.remove('hide');

  if (r.correct) onRight(q, r, inp);
  else onWrong(q, r, typed, inp);
}

// 记下这一题的作答结果（供「查看上一个」回看、以及收尾统计）
function recordAnswer(q, r, typed) {
  S.asked++;
  if (q.firstTry === null || q.firstTry === undefined) q.firstTry = r.correct;
  q.result = {
    correct: r.correct, skipped: !!r.skipped, retried: !!r.retried,
    typed: typed, answer: r.answer, ph: r.ph,
    from: r.from, mastery: r.mastery,
  };
}

// 答对
function onRight(q, r, inp) {
  S.done.add(q.id);
  inp.className = 'ok';
  $('#qFb').innerHTML = rightHtml(r);
  speak(r.answer);
  updateProgress();
  if (S.auto) S.autoTimer = setTimeout(nextQuestion, 800);   // 开了自动跳才跳
}

// 答错 / 跳过
function onWrong(q, r, typed, inp) {
  q.wrong = true;
  if (S.wrongWords.indexOf(q.en) < 0) S.wrongWords.push(q.en);
  inp.className = 'bad';
  $('#qFb').innerHTML = wrongHtml(r, typed);
  checkOtherWord(typed, r.answer);      // 打错了？看看你打的是不是另一个真词
  speak(r.answer);
  showRetype();                         // 当场给一块地方，跟着打一遍加深印象
  // 塞回本轮队尾重考，不限次数（想提前结束就点「结束本轮」）
  S.queue.push(Object.assign({}, q, { retry: true }));
}

// 答对的反馈（跟 wrongHtml 对称）
function rightHtml(r) {
  return '<div class="row"><span class="ok-t">✓ 答对</span></div>' +
    '<div class="row"><span class="lab">答案</span><span class="ans">' + esc(r.answer) + '</span>' +
    (r.ph ? '<span class="ph">' + esc(r.ph) + '</span>' : '') + '</div>' +
    '<div class="row"><span class="lab">掌握度</span><span class="fbhint">' +
    r.from + ' → ' + r.mastery +
    (r.retried ? '（重考答对，不计分）' : '（+' + r.delta + '）') + '</span></div>';
}

function wrongHtml(r, typed) {
  let mineHtml, ansHtml;
  if (r.diff) {
    mineHtml = r.diff.typed.map((c) => (c.ok ? esc(c.c) : '<em>' + esc(c.c) + '</em>')).join('');
    ansHtml = r.diff.answer.map((c) => (c.ok ? esc(c.c) : '<em>' + esc(c.c) + '</em>')).join('');
  } else {
    mineHtml = esc(typed.trim());
    ansHtml = esc(r.answer);
  }
  return '<div class="row"><span class="bad-t">' + (r.skipped ? '已跳过' : '✕ 拼写错误') + '</span></div>' +
    (mineHtml ? '<div class="row"><span class="lab">你写的</span><span class="mine">' + mineHtml + '</span></div>' : '') +
    '<div class="row"><span class="lab">正确答案</span><span class="ans">' + ansHtml + '</span>' +
    (r.ph ? '<span class="ph">' + esc(r.ph) + '</span>' : '') + '</div>' +
    '<div class="fbhint">掌握度 ' + r.from + ' → ' + r.mastery + '</div>';
}

/**
 * 答错时看看你打进去的那个是不是「另一个真实存在的单词」（不限于词库里已有的）。
 * 是的话把它连同释义显示出来，并给一个「＋ 加入词库」。
 * 判定与查询都在后端做，这里只负责显示；查不到就什么都不出现。
 */
async function checkOtherWord(typed, answer) {
  const box = $('#otherWord');
  if (!box) return;
  const w = (typed || '').trim();
  const ans = (answer || '').trim();
  if (!w || w.toLowerCase() === ans.toLowerCase()) return;

  const myIdx = S.idx;                       // 记住是哪一题，切题后回来的结果要丢掉
  box.hidden = true;

  let r;
  try { r = await api('POST', '/api/check-word', { en: w }); } catch (e) { return; }
  if (S.idx !== myIdx || !r || !r.found) return;

  box.innerHTML =
    '<span>你写的 <b>' + esc(r.en) + '</b> 是另一个词：' +
    (r.pos ? '<span class="otherpos">' + esc(r.pos) + '</span> ' : '') + esc(r.cn) + '</span>' +
    (r.in_library
      ? '<span class="dim">已在词库中</span>'
      : '<button class="link" id="otherAddBtn">＋ 加入词库</button>');
  box.hidden = false;

  const btn = $('#otherAddBtn');
  if (!btn) return;
  btn.onclick = async () => {
    btn.disabled = true;
    btn.textContent = '加入中…';
    try {
      await api('POST', '/api/words', { en: r.en, cn: r.cn, pos: r.pos, ph: r.ph });
      btn.outerHTML = '<span class="dim">✓ 已加入词库</span>';
      toast('已加入词库：' + r.en, 'ok');
      loadStats();
    } catch (e) {
      btn.disabled = false;
      btn.textContent = '＋ 加入词库';
      toast('加入失败：' + e.message, 'bad');
    }
  };
}

function nextQuestion() {
  clearTimeout(S.autoTimer);
  S.idx++;
  if (S.idx >= S.queue.length) { finishSession(false); return; }
  renderQuestion();
}

async function finishSession(early) {
  clearTimeout(S.autoTimer);
  setIme(false);
  if (S.sessionId) {
    try { await api('POST', '/api/session/finish', { session_id: S.sessionId }); } catch (e) { /* 无所谓 */ }
    S.sessionId = null;
  }

  const uniq = new Map();
  S.queue.forEach((q) => { if (!uniq.has(q.id)) uniq.set(q.id, q); });
  const words = Array.from(uniq.values());
  const firstRight = words.filter((q) => q.firstTry === true).length;
  const total = words.length || S.total || 0;
  const rate = total ? Math.round(firstRight / total * 100) : 0;
  const cls = rate >= 90 ? '' : (rate >= 70 ? 'low' : 'bad');

  let html = '<div class="sum">';
  html += '<h2>本轮结束' + (early ? '（提前结束）' : '') + '</h2>';
  html += '<div class="sumline"><span class="big-num ' + cls + '">' + rate + '%</span>' +
          '<span>一次答对　' + firstRight + ' / ' + total + ' 个词</span></div>';
  html += '<div class="sumline">总共作答 <b>' + S.asked + '</b> 次　·　已掌握 <b>' +
          S.done.size + '</b> / ' + total + '</div>';
  if (S.wrongWords.length) {
    html += '<div class="sumline" style="margin-top:16px">以下单词未能一次答对，其掌握度已下调，后续出现频率会提高：</div>';
    html += '<div class="wronglist">' + S.wrongWords.map(esc).join('　') + '</div>';
  } else if (total) {
    html += '<div class="sumline" style="margin-top:16px;color:var(--ok)">全部一次答对。</div>';
  }
  html += '<div class="sumact"><button class="primary" id="againBtn">再来一轮</button>' +
          '<button class="link" id="toLibBtn">去词库看看</button></div></div>';

  $('#study-done').innerHTML = html;
  showPhase('done');
  $('#againBtn').onclick = () => { showPhase('ready'); loadStats(); };
  $('#toLibBtn').onclick = () => showView('lib');
  loadStats();
}


/* ==================== 背诵页的元素绑定 ==================== */

function bindStudy() {

  // 数量加减
  // 数量加减
  document.querySelectorAll('.sizer .step').forEach((b) => {
    b.onclick = () => {
      const inp = $('#sizeInput');
      const v = (parseInt(inp.value, 10) || 0) + parseInt(b.dataset.step, 10);
      inp.value = Math.max(1, v);
    };
  });

  // 开始 / 结束
  $('#startBtn').onclick = startSession;
  $('#endBtn').onclick = () => finishSession(true);

  // 自动跳开关
  // 自动跳开关
  $('#autoTrack').parentElement.onclick = () => {
    S.auto = !S.auto;
    $('#autoTrack').classList.toggle('on', S.auto);
    if (S.auto && S.submitted) S.autoTimer = setTimeout(nextQuestion, 800);
  };

  // 朗读
  // 朗读
  $('#qSpk').onclick = (e) => {
    e.stopPropagation();
    const q = S.queue[S.idx];
    if (q && S.submitted) speak(q.en);
  };

  // 键盘
  // 键盘
  document.addEventListener('keydown', (e) => {
    if (S.view !== 'study' || S.phase !== 'quiz') return;

    // 焦点在跟打框里时，由它自己处理键盘（全局快捷键让路）
    if (document.activeElement && document.activeElement.id === 'retypeInput') return;

    // 回看弹层开着的时候，别让答题的快捷键跟着乱动
    if (!$('#prevModal').hidden) {
      if (e.key === 'Escape') { e.preventDefault(); closePrev(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); $('#prevOlder').click(); }
      return;
    }
    if (e.key === 'ArrowUp') { e.preventDefault(); openPrev(); return; }
    if (e.key === 'Enter' && e.ctrlKey) { e.preventDefault(); submit(true); return; }
    if (e.key === 'Enter') {
      e.preventDefault();
      if (!S.submitted) submit(false); else nextQuestion();
      return;
    }
    if (e.code === 'Space' && S.submitted) { e.preventDefault(); nextQuestion(); return; }
    if (S.submitted && e.key && e.key.length === 1) e.preventDefault();
  });

  // 输入法检测：中文输入法会发 composition 事件
  // 输入法检测：中文输入法会发 composition 事件
  document.addEventListener('compositionstart', () => {
    if (S.view === 'study' && S.phase === 'quiz' && !S.submitted) $('#imeWarn').hidden = false;
  }, true);
  document.addEventListener('compositionend', () => {
    setTimeout(() => { $('#imeWarn').hidden = true; }, 250);
  }, true);

  // 跟打框：回车判定并清空（可多遍）；空着按空格 = 下一题；Esc 退出
  // 跟打框：回车判定并清空（可多遍）；空着按空格 = 下一题；Esc 退出
  $('#retypeInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); checkRetype(); return; }
    if (e.code === 'Space' && !e.target.value.trim()) { e.preventDefault(); nextQuestion(); return; }
    if (e.key === 'Escape') { e.preventDefault(); e.target.blur(); }
  });

  // 查看上一个
  $('#prevBtn').onclick = openPrev;
  $('#prevOlder').onclick = () => { if (prevCursor > 0) { prevCursor--; renderPrev(prevCursor); } };
  $('#prevClose').onclick = closePrev;
}
