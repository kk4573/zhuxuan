/* 竹喧 · 设置
 * 设置弹层（API Key 只进不出）、输入法开关、真正退出应用。
 */

async function openSettings() {
  try {
    const c = await api('GET', '/api/config');
    $('#setIme').checked = !!c.force_english_ime;
    $('#setAccent').value = c.audio_accent || 'us';
    $('#setKey').value = '';
    $('#setKey').placeholder = c.deepseek_ready ? '已配置（留空则保持不变）' : 'sk-…（留空则不用 AI 兜底）';
    $('#cfgPath').textContent = c.config_path;
    msg('#settingsMsg', '');
    $('#settingsModal').hidden = false;
  } catch (e) { toast('读取设置失败：' + e.message, 'bad'); }
}

async function saveSettings() {
  const body = {
    force_english_ime: $('#setIme').checked,
    audio_accent: $('#setAccent').value,
  };
  const key = $('#setKey').value.trim();
  if (key) body.deepseek_api_key = key;
  try {
    const c = await api('PUT', '/api/config', body);
    $('#setKey').value = '';
    $('#setKey').placeholder = c.deepseek_ready ? '已配置（留空则保持不变）' : 'sk-…（留空则不用 AI 兜底）';
    msg('#settingsMsg', '已保存' + (c.deepseek_ready ? '　·　AI 兜底已可用' : ''), 'ok');
  } catch (e) { msg('#settingsMsg', e.message, 'bad'); }
}


/* ==================== 设置 / 退出的绑定 ==================== */

function bindSettings() {

  // 设置弹层
  $('#settingsBtn').onclick = openSettings;
  $('#settingsCancel').onclick = () => { $('#settingsModal').hidden = true; };
  $('#settingsOk').onclick = saveSettings;
  $('#setKey').addEventListener('keydown', (e) => { if (e.key === 'Enter') saveSettings(); });

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
