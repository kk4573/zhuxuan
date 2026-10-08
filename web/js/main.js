/* 竹喧 · 启动
 * 视图切换绑定 + 各页面各自绑定 + 首次加载。
 */

/* ==================== 顶部标签 ==================== */

function bindTabs() {

  // 切换 开始背 / 词库
  document.querySelectorAll('.tab').forEach((t) => { t.onclick = () => showView(t.dataset.view); });
}

/* ==================== 启动 ==================== */

function init() {
  bindTabs();
  bindCore();
  bindStudy();
  bindLib();
  bindSettings();
  bindLook();
  bindBooks();
  bindWordPop();


  // 首次加载
  loadStats();
  showPhase('ready');

  // 悄悄查一次有没有新版本（失败了什么都不显示，不影响使用）
  setTimeout(checkUpdate, 1500);
  // 允许用 #lib / #look 直接落到某个页面（调试和截图方便）
  const h = (location.hash || '').replace('#', '');
  if (['study', 'lib', 'look'].includes(h)) showView(h);
}

init();
