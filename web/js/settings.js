/* 竹喧 · 设置
 * 设置弹层（API Key 只进不出）、输入法开关、真正退出应用。
 */

async function openSettings() {
  try {
    const c = await api('GET', '/api/config');
    $('#setIme').checked = !!c.force_english_ime;
    $('#setAccent').value = c.audio_accent || 'us';
    $('#setDecay').value = (c.today_decay === undefined ? 1 : c.today_decay);
    $('#setPosLimit').value = String(c.pos_limit === undefined ? 0 : c.pos_limit);
    $('#setMeaningCount').value = String(c.meaning_count === undefined ? 2 : c.meaning_count);
    $('#setKey').value = '';
    $('#setKey').placeholder = c.deepseek_ready ? '已配置（留空则保持不变）' : 'sk-…（留空则不用 AI 兜底）';
    $('#cfgPath').textContent = c.config_path;
    loadCacheCount();
    msg('#settingsMsg', '');
    $('#settingsModal').hidden = false;
  } catch (e) { toast('读取设置失败：' + e.message, 'bad'); }
}

async function saveSettings() {
  const body = {
    force_english_ime: $('#setIme').checked,
    audio_accent: $('#setAccent').value,
    today_decay: parseFloat($('#setDecay').value),
    pos_limit: parseInt($('#setPosLimit').value, 10) || 0,
    meaning_count: parseInt($('#setMeaningCount').value, 10) || 2,
  };
  if (!isFinite(body.today_decay)) body.today_decay = 1;
  const key = $('#setKey').value.trim();
  if (key) body.deepseek_api_key = key;
  try {
    const c = await api('PUT', '/api/config', body);
    $('#setKey').value = '';
    $('#setKey').placeholder = c.deepseek_ready ? '已配置（留空则保持不变）' : 'sk-…（留空则不用 AI 兜底）';
    if (c.cn_style_changed) {
      msg('#settingsMsg', '已保存。释义详细程度变了 —— 已有单词要点上面的「重新生成释义」才会更新。', 'ok');
    } else {
      msg('#settingsMsg', '已保存' + (c.deepseek_ready ? '　·　AI 兜底已可用' : ''), 'ok');
    }
  } catch (e) { msg('#settingsMsg', e.message, 'bad'); }
}


/**
 * 按当前的释义详细程度，把所有单词的释义重跑一遍。
 *
 * 后端一次只做一批（40 个词，避免一个请求卡太久），这里翻页循环调用，
 * 顺便在按钮上显示进度。中途可以正常背单词，跑完再刷新词库列表。
 */
async function refreshCn() {
  const btn = $('#setRefreshCn');
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = '准备…';
  let page = 1, done = 0, total = 0;
  try {
    for (let guard = 0; guard < 500; guard += 1) {
      const r = await api('POST', '/api/words/refresh-cn', { page: page, size: 40 });
      done += r.done || 0;
      total = r.total || 0;
      btn.textContent = done + ' / ' + total;
      if (!r.size || page * r.size >= total || !r.done && !r.failed.length) break;
      page += 1;
    }
    msg('#settingsMsg', '已按新设置重新生成 ' + done + ' 个词的释义', 'ok');
    toast('释义已更新', 'ok');
    if (typeof loadWords === 'function') loadWords();
  } catch (e) {
    msg('#settingsMsg', '重新生成失败：' + e.message + '（可以再点一次接着跑）', 'bad');
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}


async function loadCacheCount() {
  const el = $('#cacheCount');
  if (!el) return;
  try {
    const r = await api('GET', '/api/cache');
    el.textContent = r.count;
  } catch (e) {
    el.textContent = '—';
  }
}


/* ==================== 设置 / 退出的绑定 ==================== */

function bindSettings() {

  // 设置弹层
  $('#settingsBtn').onclick = openSettings;
  $('#settingsCancel').onclick = () => { $('#settingsModal').hidden = true; };
  $('#settingsOk').onclick = saveSettings;
  $('#setKey').addEventListener('keydown', (e) => { if (e.key === 'Enter') saveSettings(); });
  $('#setRefreshCn').onclick = refreshCn;

  // 清空查词缓存（只清缓存，词库和学习记录不动）
  $('#clearCache').onclick = async () => {
    const n = $('#cacheCount').textContent;
    const yes = await askConfirm('清空查词缓存',
      '将删除本机缓存的 ' + n + ' 个查词结果。\n词库、掌握度、学习记录都不会受影响；' +
      '这些词下次查询时会重新联网取。', '清空');
    if (!yes) return;
    const btn = $('#clearCache');
    btn.disabled = true;
    try {
      const r = await api('DELETE', '/api/cache');
      toast('已清空 ' + r.removed + ' 条查词缓存', 'ok');
      loadCacheCount();
    } catch (e) {
      toast('清空失败：' + e.message, 'bad');
    } finally {
      btn.disabled = false;
    }
  };

  // 退出应用
  $('#quitBtn').onclick = async () => {
    const yes = await askConfirm('退出竹喧',
      '关掉窗口只是在后台待着，这里才是真正的退出。确定退出吗？', '退出');
    if (!yes) return;
    setIme(false);                       // 先把输入法还原
    document.body.innerHTML =
      '<div class="bye">正在退出<span>窗口马上会自己关掉</span></div>';
    try { await api('POST', '/api/quit'); } catch (e) { /* 服务正在退出，属正常 */ }
    // 后端会用 Win32 把窗口关掉；这里再用 JS 试一次作为兜底
    setTimeout(() => { try { window.close(); } catch (e) { /* 浏览器可能不允许，无所谓 */ } }, 500);
  };
}
