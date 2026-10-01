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


  // 首次加载
  loadStats();
  showPhase('ready');
}

init();
