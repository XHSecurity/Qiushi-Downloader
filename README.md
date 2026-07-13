# 求是刊读下载器 (Qiushi Downloader)

## v1.1.1 更新（修复列表行显示异常）

之前反馈的"标题和状态文字之间有一条空条"，实际原因不是进度条本身，而是：
每一行的高度（`QListWidgetItem.setSizeHint`）是在这一行的控件**还没有真正接入列表、
样式表尚未生效**的时候就算好了，导致算出来的高度偏小，副标题那一行文字被挤到卡片
底部边框以外，落进了列表项之间的间隙里——看起来就像是标题下面多了一条空杠。

修复方式：
- 把 `setSizeHint` 挪到 `setItemWidget` **之后**再计算，这样量的是控件真正接入界面、
  样式表生效之后的实际高度
- 给每行加了明确的最小高度兜底
- 进度条出现/消失时，行高会实时重新计算并同步给列表项（之前下载中状态也可能出现
  同类裁切问题，现在一并修好）

## v1.1.0 更新

- 修复：期号列表里"尚未下载"状态下会残留一条空进度条的显示问题（进度条现在只在真正下载时才占用布局空间）
- 修复：界面统一指定了跨平台中文字体优先级列表（PingFang SC / 微软雅黑 / Noto Sans CJK SC 等），
  避免个别系统上因缺少首选字体导致的中文字形错位/异体字问题
- 新增：应用图标（`assets/icon.png` / `.ico` / `.icns`，`assets/make_icon.py` 可重新生成）
- 新增：原生菜单栏——「关于」「偏好设置…」(⌘,) 「退出」「打开保存文件夹」「访问求是网」
- 新增：「关于」对话框（应用图标、版本号、作者与版权信息、内容来源免责声明）
- 新增：窗口底部常驻版权/免责声明文字
- 新增：MIT 许可证文件 `LICENSE`（工具代码本身的许可，刊物内容版权仍归原刊物方所有）
- 完善：设置面板中的"自动检查新一期"开关现在真正接线生效（`QTimer` 按设置的小时数轮询，
  发现尚未下载的最新一期会自动开始下载并写日志）

自动抓取求是网 (www.qstheory.cn) 已发布的《求是》期刊内容，按期生成排版精美的 PDF，
并以**该期实际发布日期和时间**命名保存，例如：

```
2026-07-01_09-00-00_求是_2026年第13期.pdf
```

跨平台桌面应用（macOS / Windows / Linux），基于 Python + PySide6（Qt6），
界面随系统浅色/深色主题自动切换，macOS 下遵循原生控件观感。

---

## 为什么不是抓取 ebook.qstheory.cn 的翻页阅读器？

你提供的第二个链接 `ebook.qstheory.cn/elecPublish/...` 是一个纯前端 JS 单页应用
（翻页式电子刊阅读器），内容通过阅读器内部私有接口异步加载，没有公开、稳定的文档化
API，逆向它通常需要跑一个真实浏览器内核去拦截网络请求，脆弱且容易在阅读器改版后失效。

实际调查发现，**www.qstheory.cn 本身的期刊目录页和文章页是服务端直出的静态 HTML**
（例如 `qstheory.cn/qs/mulu.htm` → 年度目录 → 期号目录 → 逐篇文章），信息与
电子刊阅读器完全一致（标题、作者、正文、配图、发布时间），且更适合稳定抓取。因此本程序
以此为数据源，把每期目录下的全部文章重新排版为一份完整 PDF（封面 + 目录 + 正文），
效果上等价于"下载电子刊"，但实现更稳固。

数据来源被抽象成一个插件接口（见下方"扩展"一节），如果你之后仍想接入
`ebook.qstheory.cn` 的翻页图片流，或接入其它刊物站点，只需新增一个
`SourcePlugin` 实现即可，无需改动 UI 或 PDF 生成逻辑。

## ⚠️ 关于测试的重要说明

本项目是在一个**无法直接访问 qstheory.cn 的沙盒环境**中编写的：我通过一个只读的网页
抓取工具确认了真实网站的 URL 结构、目录页格式和发布时间格式（这些都已经写进了
`scraper.py` 的正则表达式与抓取逻辑里，可信度较高），但**没有条件在原始 HTML 上逐个
核对文章正文容器的 CSS 选择器**（网页抓取工具只返回了转换后的正文文本，看不到真实的
`class`/`id`）。

因此：

- `models.py`、`config.py`、`downloader.py`、`pdf_builder.py`、UI 部分——已在本地
  完整跑通（成功用 QtWebEngine 生成过一份真实 PDF，见下方"已验证"）。
- `scraper.py` 里目录/年份的解析逻辑基于抓到的真实页面文本模式编写，把握较大；
  但**文章正文提取用的 `CONTENT_SELECTORS` 列表是"尽量覆盖常见 CMS 结构 + trafilatura
  兜底"的防御式写法**，请在你自己能联网的机器上，第一次使用前先跑一次自检：

  ```bash
  python scraper.py --selftest
  ```

  它会打印抓到的年份数、最新一期的文章数量和前几篇标题。如果文章数是 0 或标题明显不对，
  多半是网站正文容器的 class 名和预设的不一样，把打印出的失败 URL 的原始 HTML
  发给我（或自己 F12 看一下正文外层 `<div>` 的 class/id），加进 `CONTENT_SELECTORS`
  列表最前面即可，不需要改其它任何代码。

### 已验证可正常工作

- PDF 生成管线（HTML → Chromium 排版 → PDF）：本地已用 QtWebEngine 成功渲染出
  3 页 PDF（封面/目录/正文各一页），中文字体、分页、图片占位均正常。
- 年度目录页 → 期号目录页 → 文章页的 URL 结构：来自对真实页面的实际抓取结果，
  而非猜测。
- 期刊发布日期时间的正则（用于文件命名）：来自真实页面文本
  `来源：《求是》2026/13 2026-07-01 09:00:00` 的实际格式。

---

## 安装

需要 Python 3.10+。

```bash
cd qiushi_downloader
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 运行

```bash
python main.py
```

首次运行会在"文稿/Documents/QiuShi_PDF"下创建保存目录（可在设置里更改）。

## 打包为独立 App（可选）

macOS（生成 .app）：

```bash
pip install pyinstaller
pyinstaller --windowed --name "求是刊读下载器" \
  --icon assets/icon.icns \
  main.py
```

Windows（生成 .exe）同理，把 `--icon` 换成 `.ico` 文件即可；PyInstaller 对
PySide6 + QtWebEngine 的支持是现成的，无需额外配置。

---

## 功能

- 按年份浏览、按期下载，或"下载本年全部"
- 每期一个进度条：抓取文章 → 排版渲染 → 完成，状态实时可见
- 文件名 = 该期**真实发布日期时间** + 期号，已存在的文件自动跳过、不重复下载
- 界面浅色/深色跟随系统（macOS/Windows/Linux 均可），也可在设置里手动指定
- 设置项：PDF 保存位置、抓取请求间隔（避免请求过快）、内容来源、自动检查开关与频率
- 后台线程做全部网络请求，UI 全程不卡顿；PDF 渲染通过线程安全的"桥接"对象
  安全地跑在 GUI 线程（QtWebEngine 的硬性要求）

## 扩展点（预留的功能扩展空间）

| 想做什么 | 改哪里 |
|---|---|
| 接入新的期刊/站点 | 在 `scraper.py` 里新增一个 `SourcePlugin` 子类并 `@registry.register`，设置里的"内容来源"下拉框会自动出现 |
| 改 PDF 版式/配色 | `pdf_builder.py` 里的 `_CSS` 字符串，纯 CSS，改完即所见即所得 |
| 定时自动检查新一期 | `config.py` 已有 `auto_check_enabled` / `auto_check_interval_hours` 两个持久化配置项和设置面板 UI；`main.py` 里挂一个 `QTimer` 定期调用 `worker.request_years()` 即可接上（当前版本已留好开关，仅差最后接线，方便你按自己需要的触发策略——例如"仅新期发布后 1 小时再抓，给网站排版留出时间"——去实现） |
| 换一种 PDF 渲染方式 | 只需替换 `PdfRenderer.render()` 的实现（当前用 QtWebEngine/Chromium），`PdfBridge`、`downloader.py` 完全不用动 |
| 失败重试策略、限速策略 | `downloader.py` 的 `_handle_download` 是唯一的下载状态机入口 |

## 目录结构

```
qiushi_downloader/
├── main.py            # 入口
├── config.py           # 持久化设置（QSettings，跨平台原生存储位置）
├── models.py            # Issue / Article 数据结构
├── scraper.py            # 抓取逻辑 + 插件基类/注册表（含 --selftest）
├── pdf_builder.py         # HTML 排版 + QtWebEngine 渲染为 PDF
├── downloader.py           # 后台线程调度、文件命名、状态机
├── ui/
│   ├── theme.py             # 跟随系统的浅/深色主题
│   └── main_window.py        # 主界面
└── requirements.txt
```

## 合规提醒

《求是》是公开发布的官方期刊网页内容，本工具仅做**个人本地归档/离线阅读**用途的自动化整理，
请遵守 qstheory.cn 网站声明及 robots 规则，抓取时保持默认的请求间隔（设置中可调），
不要用于大规模再分发。
