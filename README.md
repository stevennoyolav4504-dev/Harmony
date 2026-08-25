# Harmony — Instagram & YouTube 多媒体下载器

[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](https://github.com/yourname/harmony/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)]()
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> 开箱即用的桌面工具，支持 **Instagram 图片/视频提取** 与 **YouTube 高清下载**。  
> 内置现代化暗色/亮色主题、多选预览、批量下载、历史记忆，专为粉丝设计。

---

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

### 📸 Instagram 媒体提取
- 精准抓取帖子图片、视频、轮播图与 Reels
- 自动过滤推荐帖、头像等干扰项
- 卡片网格预览，单击选择/取消，右键全尺寸预览
- 全选、复制链接、批量并行下载
- 自动保存最近 10 条提取记录，含缩略图缓存

### 🎬 YouTube 下载器
- 支持 4K / 2K / 1080p / 720p / 480p / 360p
- 可选编码：H.264 / H.265 (HEVC) / AV1 / VP9
- 输出格式：mp4 / mkv / webm
- 片段裁剪、SRT 字幕下载
- 自动复用登录态，降低风控

### 🎨 用户体验
- 一键登录，自动捕获 Cookie
- 暗色/亮色主题一键切换
- 支持 HTTP 代理
- Windows / macOS / Linux 跨平台

---

## 🚀 快速开始

### 普通用户（推荐）

1. **下载**：前往 [Releases](https://github.com/stevennoyolav4504-dev/Harmony/releases) 下载最新版本的 `Harmony.zip`
2. **解压**：解压到你想要的任意位置
3. **运行**：双击 `Harmony.exe` 即可启动

> 💡 **就是这么简单！** 不需要安装 Python，不需要敲任何命令。

### 首次使用

程序启动后，你需要准备一个 `cookies.json` 文件（用于 Instagram 登录）：

- **方式一（推荐）**：点击程序内的 **一键登录** 按钮，按提示操作即可自动完成
- **方式二（手动）**：安装浏览器扩展 [Cookie-Editor](https://chrome.google.com/webstore/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm)，登录 Instagram 后导出 Cookie（JSON 格式），保存为 `cookies.json` 放在程序根目录

> YouTube 下载会自动复用 Instagram 的 Cookie，无需额外配置。

---

## 🛠️ 开发者指南

如果你想自己运行源码或进行二次开发：

```bash
git clone https://github.com/yourname/harmony.git
cd harmony
pip install -r requirements.txt
playwright install chromium
python main.py
```

详细说明请参考 [开发者文档](DEVELOPER.md)（如有）。

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

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

如果你有好的功能建议，欢迎在 Issue 中讨论。

---

## 📄 开源协议

本项目采用 [MIT License](LICENSE)。

---

**Made with ❤️, for QWER.**

*“我们用代码，收藏那些让我们心动的频率。”*
