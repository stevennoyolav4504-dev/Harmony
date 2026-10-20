# Harmony 2.2 — Instagram / X / TikTok & YouTube 多媒体下载器

[![Version](https://img.shields.io/badge/version-2.2.4-F454A4.svg)](https://github.com/stevennoyolav4504-dev/Harmony/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)]()
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> 开箱即用的桌面工具，支持 **Instagram / X / TikTok 图片和视频提取** 与 **YouTube 视频并行下载**。
> 内置现代化暗色/亮色主题、多选预览、批量下载、历史记忆，专为粉丝设计。

---

## 2.2 更新

2.2.4 保留正常后台提取；IG 预览重试后仍有失败项时，自动打开有头浏览器，跳过快速 JSON 数据，按旧版逐页轮播重新提取一次。使用新地址补救失败项并更新下载地址，保留已成功的图片、原列表与勾选。正在下载时会等待完成再补救，单次提取最多自动启动一次，不循环弹窗；打开有失败预览的 IG 历史记录也会针对该帖补救。

87 项回归测试通过。本地故障页面配合 agent-browser 有头会话，验证两项持续失败的预览通过实际轮播恢复、选择及好图不变，选中原文件下载校验通过；未据此宣称线上故障帖已恢复。

2.2.3 为预览和媒体下载加入自动重试，短暂断连、超时、SSL 提前断开、不完整响应及临时服务器错误最多重试 2 次，保留 TLS 证书验证。成功项不重复下载，失败的临时文件会被清理，已有完整文件保留。IG / X 下载沿用设置中的代理，预览失败不再显示“仍可下载”，下载按实际结果显示成功与失败数量；新日志使用 UTF-8 并补记提取和预览错误。

75 项回归测试及本地真实断连恢复流程通过。按用户授权复测此次失败的 4 个媒体地址，当前预览与完整下载均成功，图片文件校验通过，未改变个人配置或 Cookie；这 4 项在此前日志中属于同一 CDN 节点的连接中断。

2.2.2 将 IG 提取改为后台静默运行，正常提取不再弹出浏览器窗口。底层继续使用内置 Chromium 和原有登录信息；登录失效或需要验证时在 Harmony 内提示，只有主动前往设置点击一键登录才打开登录窗口。

66 项回归测试通过。一个真实 IG 历史帖在后台完整返回 20 张图片，含浏览器启动约 2.1 秒，不含预览或下载，仅代表该帖与当时网络；全程未观察到测试子进程的可见浏览器窗口，Cookie 文件未改变。

2.2.1 优化 IG 提取：只有确认属于当前帖子的完整媒体数据时才直接返回，其他情况保留原轮播流程。固定等待改为内容就绪等待；先显示媒体卡片，预览随后逐张补齐，可立即选择、复制或下载，保持原图与全尺寸预览。

63 项回归测试及本地新旧页面对比通过。一个实际历史帖的提取阶段从约 46 秒降至约 1.5–3 秒，并补齐旧版漏掉的 1 个视频；该帖完整数据为 10 图、1 视频，原 10 图顺序一致。比较在已启动的独立浏览器中进行，包含导航，不含浏览器启动或预览加载，仅代表该帖与当时网络。

2.2.0 在原有 IG 模块加入 TikTok，支持公开视频、图片帖与 vm、vt、`/t/` 分享短链接。图片按原顺序显示，沿用多选、右键预览、下载和历史记录；打开 TikTok 历史时重新提取，刷新有时效的下载地址。

TikTok 解析、封面和下载沿用设置中的代理，读取已有 cookies.json 中的 TikTok 域 Cookie，不修改原文件。私密、删除、登录、地区或网络受限的帖子可能无法提取。此次线上验证收到 TikTok 的 10204 网络拒绝；离线样本和本地真实媒体下载流程验证通过，不据此宣称当前网络上的 TikTok 下载已验证成功。

2.1.0 在媒体提取页加入 X / Twitter 帖子解析；视频页新增多行批量输入和下载队列，默认同时下载 3 个，可调整为 1–5 个。每项独立显示进度，支持下载期间继续添加、取消、失败重试与打开目录。

任务保存加入队列时的目录、画质、格式、编码、片段、字幕和登录状态，后续修改不会影响已有任务。调低并发数后，正在下载的任务继续完成，后续任务按新上限启动。同一视频加入同一目录的活动任务自动去重；不同视频同名时分别保存，片段处理保留已有完整视频。

2.0.8 将内置 yt-dlp 更新为官方 nightly 2026.10.10.233141，配套 EJS 0.8.0 与完整解析脚本；源码和 Windows 程序包使用同一版依赖。核对时官方正式版仍为 2026.08.19，此次更新明确使用 nightly 通道。

2.0.7 在最小化前保留完整窗口画面，恢复最初几帧复用它，待控件完成绘制后释放；输入、点击和任务进度继续使用原有控件。

2.0.6 减少窗口恢复时的绘制延迟：缓存装饰表面、取消整窗透明动画，恢复时保留现有控件、输入和滚动位置。

2.0.5 按 9 月 24 日新版参考图重做：粉白柔和背景、白色圆角卡片、蓝色渐变提取按钮、粉色渐变下载按钮、彩色圆形步骤标记、立体平台插画与虚线空状态。应用图标继续使用 REV.06 官方素材，提取与下载流程保持原有行为。

2.0.4 统一界面视觉：浅粉主背景、白色卡片、蓝色操作与选中状态、绿色下载与完成状态，配套深灰外观。字体优先使用 Noto Sans SC，按钮、弹窗、菜单与空状态同步更新。

2.0.3 按 REV.06 品牌手册更新标识：应用图标使用浅粉主背景与官方四色图形标（72% 占比），侧栏使用官方文字标，帮助页使用标准组合标，并统一弹窗图标。详见 [品牌素材说明](src/assets/brand/README.md)。

新版采用品牌色卡片布局、文字侧边栏与顶部平台切换，并使用官方四色云下载图标。
新增 YouTube「解析视频」入口，修复片段时间输入、本地目录选择及外观切换后的状态恢复。

- [2.2.4 下载](https://github.com/stevennoyolav4504-dev/Harmony/releases/tag/v2.2.4)
- [完整更新日志](CHANGELOG.md)
- 升级时先退出旧版，将新版解压到新文件夹；如需保留设置，可将自己的 `config.json`、`cookies.json`、`youtube_cookies.txt` 和 `.image_cache` 复制到新版程序旁。发布包不包含个人配置或登录数据。

## 🎵 关于名字

**Harmony** 这个名字，源于一个简单的愿望。

当我第一次用代码搭建这个工具时，只想更近地追随一支叫 **QWER** 的乐队。她们的音乐像某种联结，每次听到都让人感到平静和共鸣——一种很纯粹的 **和谐（Harmony）**。

这个工具不是为了“破解”或“滥用”，而是让我（以及像我一样的听众）能把自己喜欢的片段、MV、日常碎片保存下来。在某个安静的时刻，可以随时翻开，重听那段旋律，重看那个瞬间。

所以它叫 **Harmony**——一个收集美好的地方。

> “我们用代码，收藏那些让我们心动的频率。”

---

## 🎸 特别致谢：QWER

如果你也是 QWER 的听众，希望它能帮你更好地保存那些值得反复回看的片段。

[![Instagram](https://img.shields.io/badge/@qwer.official-E4405F?style=flat&logo=instagram&logoColor=white)](https://www.instagram.com/qwerband_official/)
[![YouTube](https://img.shields.io/badge/QWER-FF0000?style=flat&logo=youtube&logoColor=white)](https://www.youtube.com/@QWER_Band_official)

---

## ✨ 功能亮点

### 📸 Instagram / X / TikTok 媒体提取
- 精准抓取帖子图片、视频、轮播图与 Reels
- 自动过滤推荐帖、头像等干扰项
- 卡片网格预览，单击选择/取消，右键全尺寸预览
- 全选、复制链接、批量并行下载
- 自动保存最近 10 条提取记录，含缩略图缓存
- X / Twitter：公开帖子的原生图片、视频和动图（MP4），沿用选择、预览、下载与历史功能
- X 外部卡片、私密、已删除或受平台访问限制的帖子可能无法提取
- TikTok：公开视频和图片帖、分享短链接；图片按原顺序显示，沿用同一个媒体页面

### 🎬 YouTube 下载器
- 支持 4K / 2K / 1080p / 720p / 480p / 360p
- 可选编码：H.264 / H.265 (HEVC) / AV1 / VP9
- 输出格式：mp4 / mkv / webm
- 片段裁剪、SRT 字幕下载
- 自动复用登录态，降低风控
- 每行一个链接批量加入队列，同时下载 1–5 个，默认 3 个
- 各项独立进度与设置，支持继续添加、取消、失败重试及打开保存目录

### 🎨 用户体验
- 一键登录，自动捕获 Cookie
- 暗色/亮色主题一键切换
- 支持 HTTP 代理
- Windows / macOS / Linux 跨平台

---

## 🚀 快速开始

### 新功能用法

在「Instagram / X / TikTok」页粘贴帖子完整链接或 TikTok 分享短链接，点击「提取」，再选择并下载媒体。

在视频页批量输入区每行粘贴一个视频链接，选择目录、画质和格式后点击「批量下载」。可通过「同时下载」调整并发数，在任务队列查看和操作每个视频。单个链接仍可先解析标题和可用画质，再点击「下载」。

### 普通用户（推荐）

1. **下载**：前往 [Releases](https://github.com/stevennoyolav4504-dev/Harmony/releases) 下载已发布的 Windows x64 程序包
2. **解压**：解压到你想要的任意位置
3. **运行**：双击 `Harmony.exe` 即可启动

> 💡 **就是这么简单！** 不需要安装 Python，不需要敲任何命令。

### 首次使用

程序启动后，你需要准备一个 `cookies.json` 文件（用于 Instagram 登录）：

- **方式一（推荐）**：点击程序内的 **一键登录** 按钮，按提示操作即可自动完成
- **方式二（手动）**：安装浏览器扩展 [Cookie-Editor](https://chrome.google.com/webstore/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm)，登录 Instagram 后导出 Cookie（JSON 格式），保存为 `cookies.json` 放在程序根目录

> YouTube 登录状态需要 YouTube / Google 域的有效 Cookie；Instagram Cookie 本身不能用于 YouTube 登录。

---

## 🛠️ 开发者指南

如果你想自己运行源码或进行二次开发：

```bash
git clone https://github.com/stevennoyolav4504-dev/Harmony.git
cd Harmony
pip install -r requirements.txt
playwright install chromium
python src/main.py
```

### Windows 启动与打包

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m pip install pyinstaller==6.22.0
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\browsers"
.\venv\Scripts\python.exe -m playwright install chromium
.\venv\Scripts\python.exe src\main.py
```

之后可双击 `src\launch.vbs` 启动。运行 `src\build.bat` 生成 `dist/Harmony/Harmony.exe`，发布时携带整个目录。
视频转码、合并与片段下载需要 FFmpeg，可放到 `browsers/ffmpeg/ffmpeg.exe` 或加入系统 PATH。
YouTube 使用的 Node 运行时可放到 `runtime/node/<版本>/node.exe`。

界面代码位于 `src/harmony_ui.py`，绘制图标和插画的代码位于 `src/harmony_art.py`，版本位于 `src/version.py`。
运行 `.\venv\Scripts\python.exe -m unittest discover -s src/tests -v` 执行离线界面与品牌资产回归测试。


---

## ❓ 常见问题

**Q：双击 exe 没反应？**  
A：请确保解压完整，不要直接在压缩包内双击运行。如果仍然不行，可以尝试以管理员身份运行。

**Q：提示“找不到浏览器”？**  
A：请确认 `_internal/browsers` 目录存在且完整。如果缺失，可以手动运行 `playwright install chromium`。

**Q：Instagram 提取失败，提示跳转到登录页？**  
A：Cookie 已过期，请重新执行一键登录或手动更新 `cookies.json`。

**Q：YouTube 下载报 403？**  
A：确保 `cookies.json` 中包含 YouTube/Google 的有效 Cookie。程序会自动转换。

**Q：有没有使用教程？**  
A：程序界面本身比较直观，你也可以在 [Releases](https://github.com/stevennoyolav4504-dev/Harmony/releases) 页面查看演示视频（如有）。

---

## ⚠️ 注意事项

- 本工具仅供个人学习与研究使用，请勿用于商业或侵犯他人权益。
- 使用 Instagram 提取功能时，请合理控制请求频率，遵守平台服务条款。
- Cookie 文件包含登录凭证，请妥善保管，切勿公开分享。

---
🙏 鸣谢
Harmony 能够顺利诞生，离不开以下优秀开源项目的支撑：

核心依赖
yt-dlp — YouTube 下载的核心引擎，没有它，YouTube 模块无法实现。感谢开发团队持续与 YouTube 的反爬机制“斗智斗勇”。

Playwright — 让 Python 能够驱动真实浏览器，Instagram 提取的精准度依赖于它的能力。

CustomTkinter — 为 Tkinter 赋予了现代化的外观，让 Harmony 的界面拥有了暗色/亮色主题和流畅的视觉体验。

playwright-stealth — 帮助 Harmony 更好地“隐身”于浏览器环境中，降低了被反爬检测的概率。

pysubs2 — 字幕处理的得力助手，让 SRT 的解析与生成变得简单可靠。

基础工具链
Pillow — 图像处理的中流砥柱，缩略图生成、卡片渲染都离不开它。

requests — 最优雅的 HTTP 库，下载、API 请求的基础。

openai — 为未来可能集成的 AI 翻译功能预留了接口（虽然暂时还在路上）。

开源精神
感谢所有为开源社区贡献代码的开发者们。你们的每一行代码，都在让这个世界变得更好。

如果 Harmony 帮到了你，不妨也给这些项目点个 ⭐，让它们被更多人看到。

---


## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

如果你有好的功能建议，欢迎在 Issue 中讨论。

---

## 📄 开源协议

本项目采用 [MIT License](LICENSE)。

---

**Made with ❤️, for QWER.**

*“我们用代码，收藏那些让我们心动的频率。”*
