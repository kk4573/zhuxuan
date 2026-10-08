# 竹喧

> 看中文填英文的加权抽词背单词工具 · Windows 单文件 · 数据全部保存在本机

「竹喧」取自「竹喧归浣女」——竹林里有人说话，正是背单词时念念有词的画面。

**下载**：[`zhuxuan-v1.1.1.exe`](zhuxuan-v1.1.1.exe)（34.3 MB，双击即用，无需安装 Python、无需浏览器）

![背诵页](docs/screenshot-study.png)

## 下载使用

**下载这个文件：** [`zhuxuan-v1.1.1.exe`](zhuxuan-v1.1.1.exe)（34.3 MB）

### 国内网络加速（重要）

`github.com` 直连在国内基本不通（实测：请求直接超时，无法建立连接）。
把下面任一行的**全部内容**复制到浏览器地址栏回车，即可下载：

```
https://ghfast.top/https://github.com/kk4573/zhuxuan/raw/main/zhuxuan-v1.1.1.exe
```
```
https://gh-proxy.com/https://github.com/kk4573/zhuxuan/raw/main/zhuxuan-v1.1.1.exe
```

实测：第一条约 5 秒，第二条约 40 秒，直连则完全不通。
若下载后文件名乱码或缺少 `.exe` 后缀，手动改回 `zhuxuan-v1.1.1.exe` 再双击。

### 放在哪、怎么启动

放到**桌面**或任意有写入权限的文件夹，双击即可。

- **不要**放进 `C:\Program Files` 这类需要管理员权限的目录。（真放了也不会坏：
  程序检测到写不进去，会自动把数据改存到 `%LOCALAPPDATA%\竹喧`。）
- 首次双击若出现「Windows 已保护你的电脑」，点 **更多信息 → 仍要运行**。
  个人项目没有购买代码签名证书，这是误报。

### 运行环境要求

| 项目 | 要求 |
|---|---|
| **系统** | Windows 10（1803 及以上）或 Windows 11，64 位 |
| **Python** | **不需要**，程序已打包成单个 exe |
| **浏览器** | **不需要** —— 界面内嵌在程序自己的窗口里 |
| **网络** | 可选。只有查词 / 补释义 / 导入内置词表时才联网 |

界面用的是 Windows 自带的 **WebView2** 组件（Windows 10 1803+ 和 Windows 11 都是
系统的一部分），**不用另外装任何东西**，装好系统就有。

> **极少数没有 WebView2 的情况**（精简版系统、Windows Server）：
> 程序会自动退回用电脑上的浏览器打开，功能完全一样。连浏览器都没有时会弹窗提示。

### 校验文件完整性（可选）

PowerShell 里运行，输出应以 `bab30fbf` 开头：

```powershell
Get-FileHash .\zhuxuan-v1.1.1.exe -Algorithm SHA256
```

完整值：`bab30fbf16c3549f535a921eb1f36161cc74bf3c2ad28f706037bc7bc3e2a654`

### 第一次打开

**词库是空的。** 点首页的「导入词表 →」按钮，选一份内置词表
（四级 / 六级 / 考研 / 托福 / GRE）导入，就能开始背了。

### 以后怎么更新到新版本

**好消息：数据不会丢。** 程序本体和数据是分开存的：

```
你放 exe 的目录\
├── 竹喧.exe          ← 只有程序，更新时换的就是它
├── config.json       ← 设置（含 API key）
└── data\
    ├── words.db      ← 词库 + 全部学习记录
    └── backups\      ← 每次启动自动备份（保留最近 10 份）
```

数据全在 `data\` 和 `config.json` 里，**它们不叫「竹喧.exe」**，所以换掉程序碰不到它们。

#### 更新步骤

1. 下载新版 exe
2. 丢进**原来那个目录**
3. **把旧的 exe 删掉**（如果新旧文件名不一样，比如从 `竹喧.exe` 变成
   `zhuxuan-v1.1.1.exe`，一定要删旧的，不然两个图标分不清哪个是哪个）

打开就是新版。**词库、掌握度、答题记录、设置全都还在。**

#### 想更保险？

更新前把**整个文件夹复制一份**放着。出任何问题，用复制的那份覆盖回去就行。
程序自己也会在每次启动时自动备份数据库（存在 `data\backups\`，保留最近 10 份）。

#### 万一数据出问题

从 `data\backups\` 里找最近一次的备份，把它复制成 `data\words.db` 即可。
（注意：这样会把之后的学习进度一起退回去）

### 关掉窗口就是退出

点窗口的 × 或顶栏的 ⏻ 都会完整退出程序（后台服务一起停，不留残余进程）。

## 它长什么样

| 背诵 | 词库 | 查词 |
|---|---|---|
| ![背诵](docs/screenshot-study.png) | ![词库](docs/screenshot-lib.png) | ![查词](docs/screenshot-look.png) |

## 主要功能

- **看中文填英文**：给中文释义，拼出对应单词；忽略大小写与首尾空格。
- **加权抽词**：越不熟的词出现得越勤。答对涨熟练度（连对涨幅更高），答错掉一档，
  当天已经考过的词会降权，避免一天内反复刷同一个词。
- **答错不限次重考**：错词回到本轮队尾，直到当场答对。每次答错都显示正确答案。
- **拼写逐字母比对**：错了会标出哪几个字母不对（但不会直接告诉你答案）。
- **英美拼写都算对**：`colour` / `color` 一类通过别名表识别。
- **自动补全释义与音标**：输入英文即可从在线词典取释义、音标、例句，本地缓存，
  查过的词不重复联网。
- **多词库**：一个词可以同时属于多个词库，熟练度跨词库共享。内置词表按需导入。
- **例句点词**：例句里任意单词点一下弹出小框看释义，可进一步跳转查词页或加入词库。
  自动识别单复数与时态（`children → child`、`nosed → nose`）。
- **真人发音**：联网发音，可关闭。
- **数据全在本机**：词库、学习记录都是本地 SQLite 文件，不联网、不上传、没有账号。

## 数据放在哪

exe 同级的 `data/` 目录：

```
竹喧.exe
data/
  words.db      ← 词库与学习记录（唯一的数据库）
  backups/      ← 每次启动自动备份，保留最近 10 份
  edge-profile/ ← 界面用的浏览器配置
```

**换电脑或备份，直接拷整个文件夹即可。**
如果 exe 放在写不进去的地方（比如 `C:\Program Files`），数据会自动改存到
`%LOCALAPPDATA%\竹喧`。

## 自己改、自己打包

需要 Python 3.11+。

```bash
pip install fastapi uvicorn openpyxl python-multipart pyinstaller pillow pywebview

# 开发时直接跑
python app.py

# 打包成单文件 exe（产物在 dist/）
pyinstaller --noconfirm --clean --onefile --windowed --name 竹喧   --icon app.ico --add-data "web;web" --collect-all uvicorn app.py
```

代码结构：

```
app.py            FastAPI 服务 + 全部接口 + 启动窗口
core/
  db.py           SQLite 全部 SQL
  srs.py          熟练度模型与加权抽词
  judge.py        答案判定（含英美拼写别名表）
  dictionary.py   在线词典、释义整理、词形还原
  vocab.py        内置词表下载与解析
  ai.py           DeepSeek 兜底（可选，默认不用）
  ime.py          答题时锁英文输入法（Win32）
  config.py       设置项
  paths.py        路径解析（源码 / exe 两种形态）
web/              前端（原生 HTML/CSS/JS，无框架）
tests/            自测脚本
```

## 可选的 AI 兜底

**默认不启用，不影响使用。** 只有遇到在线词典完全查不到的词（新词、缩写、专有名词）
才需要它生成释义。如果你有自己的 DeepSeek API Key，可以在设置里填入，
Key 只保存在本机 `config.json`，程序不会把它发往任何地方。

## 许可

[MIT](LICENSE)

## 致谢

- 内置词表来自 [mahavivo/english-wordlists](https://github.com/mahavivo/english-wordlists)
- 释义与发音来自有道词典的公开接口
