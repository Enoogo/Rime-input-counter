# Rime 输入统计 · 字数 / 按键数统计 + 交互式折线图

## 首先
**所有内容都是dsh生成的**。除了html的界面是我手动改过的，其它都是dsh搞的。这个markdown也是dsh写的，只有这段话是我写的。

所以可能有的地方会胡言乱语。因为我是一点点让它完善的，它每次都会把主要更新写到程序的注释或者markdown里面去，导致最终生成的readme的时候也融合进来了。实际上有的只是一些修复了的bug罢了，不是什么特点。这个我以后再慢慢改。

有问题可以提出，刚好让我能学习学习。虽然我大概率也是扔给dsh。但是dsh解决不了那我就只能自己研究研究了。

也欢迎大佬来随便改改。

**好了，接下来请享用纯粹的ai生成内容。**

## 概要


用 [Rime](https://rime.im/)（小狼毫 Weasel / 鼠须管 Squirrel 等）打字即自动记录**上屏字数**与**按键数**：

- 中文状态输入 **`ii`**，候选框实时显示「今日 / 总计」统计；
- 双击 **`查看每日统计.bat`**，自动生成并打开一个**单文件 HTML 折线图**，
  顶部三个标签可切换 **每日 / 按天聚合 / 按分钟聚合** 三档时间尺度；
- 数据是纯文本、append-only，不含你打的字的内容，只有「时间戳 + 字数 + 按键数」。

图表是自包含 HTML（内嵌 CSS/JS，无任何外部库和 CDN），离线可用；
Python 3 可选——没有 Python 也能用内置 PowerShell 生成器出同样的图。

---

## 功能特性

| 功能 | 说明 |
| --- | --- |
| 自动统计 | 无需常驻程序，打字即记录：上屏字数（中文/英文/标点都算）+ 拼音按键数 |
| 实时查询 | 中文状态输入 `ii`，候选框显示「今日：xx字/xx键 \| 总计：…」，`Esc` 关闭 |
| 三档图表 | **每日**（长期趋势）/ **按天聚合**（1–365 天任选组距，按周/按月看）/ **按分钟聚合**（1–1440 分钟任选组距，最细到每分钟） |
| 交互细节 | 悬停看数值、横向滚动、左右纵轴刻度始终固定可见、横轴标注日期且任何组距都不重叠、默认定位到最新数据 |
| 分钟级原始数据 | 每分钟一行 append-only，写入开销恒定，数据再多也不变慢 |
| 双生成器 | Python 版（可选 `--png` 导出）+ PowerShell 备用版，输出同样的三档图表 |
| 零依赖 | 图表 HTML 自包含，不需要联网、不需要前端框架 |
| 可移植 | 数据目录自动定位（Rime 用户目录下），拷到任何机器免改代码；也可自定义任意目录 |

---

## 效果预览（合成示例数据）

仓库自带示例数据（`sample_input_count.txt` / `sample_input_count_raw.txt`，纯合成），
不装 Rime 也可以先看看图长什么样：

```powershell
# Python 版（合成演示数据，最简单）
python plot_input_count.py --demo --output demo_chart.html

# 或用仓库自带的示例数据文件（日汇总 + 分钟级）
python plot_input_count.py --input sample_input_count.txt --raw sample_input_count_raw.txt --output demo_chart.html

# 没有 Python？PowerShell 版（注意：-Demo 请务必带 -OutputPath，否则会覆盖真实图表）
powershell -NoProfile -ExecutionPolicy Bypass -File chart_powershell.ps1 -Demo -OutputPath demo_chart.html
```

生成后浏览器自动可打开。示例数据文件同时也是**数据格式的范本**。

---

## 快速开始

### 环境要求

- 带 **librime-lua** 的 Rime 发行版（小狼毫官方版自带；本项目在 Windows + 小狼毫 0.17 上开发验证）
- **Python 3**（可选，图表首选生成器；没有也能用 PowerShell 版）
- **Windows PowerShell 5.1+**（备用图表生成器与安装脚本）

### 方式一：一键安装（推荐）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1
```

脚本会自动完成：检测 Rime 用户目录 → 安装 `lua/input_count.lua` → 合并 `rime.lua`
（旧版 librime 备用入口）→ 给方案打补丁挂上 `lua_translator@*input_count`
→ 把图表工具复制到数据目录 → 打印验证清单。已有文件一律先备份成 `*.bak`。

| 参数 | 说明 |
| --- | --- |
| `-UserDir <路径>` | 指定 Rime 用户目录（默认自动检测：注册表 `RimeUserDir` → `%APPDATA%\Rime`） |
| `-DataDir <路径>` | 数据 + 图表工具目录（默认 `<用户目录>\Rime-input-count`；指定后会把 lua 的 `data_dir_override` 一并写成该路径） |
| `-Schema <方案名>` | 要挂载统计的方案，默认 `luna_pinyin_simp` |
| `-NoToolsCopy` | 不复制图表工具到数据目录 |
| `-Deploy` | 安装后顺带尝试 `WeaselDeployer.exe /deploy`（默认不自动部署，避免弹窗卡住） |
| `-DryRun` | 只打印将要做什么，不写任何文件 |

装完后：**托盘右键 → 重新部署**，中文状态打两个 `i` 试试。

### 方式二：手动安装

1. **复制核心脚本**：把 `lua\input_count.lua` 复制到 `<Rime用户目录>\lua\`。
2. **挂载到方案**：在你的方案补丁（如 `luna_pinyin_simp.custom.yaml`）的
   `engine/translators` 列表末尾加一项 `"lua_translator@*input_count"`
   （完整示例见仓库里的 `luna_pinyin_simp.custom.yaml`；其他方案同理，
   如需往已有列表里**追加一项**，可用 Rime 的 `engine/translators/+` 语法，
   见 [Rime 配置文件文档](https://rimeinn.github.io/rime/configuration.html)）。
3. **（可选，旧版 librime 才需要）** 把 `rime.lua` 里的绑定合并进 `<Rime用户目录>\rime.lua`，
   并把方案里的 `@*input_count` 改成 `@input_count`。
4. **放置图表工具**：把 `plot_input_count.py`、`chart_powershell.ps1`、`查看每日统计.bat`
   （以及示例数据，可选）放到数据目录——默认 `<Rime用户目录>\Rime-input-count\`。
   工具按“自身所在目录”读写数据，跟数据放一起即可。
5. **重新部署**：托盘右键 →「重新部署」，或运行 `WeaselDeployer.exe /deploy`。

### 数据放在哪里（路径规则）

| 情况 | 数据写到哪 |
| --- | --- |
| 默认（什么都不用改） | `<Rime用户目录>\Rime-input-count\`，由 `rime_api.get_user_data_dir()` 自动定位 |
| 想放别的盘 / U 盘 / 同步盘 | 编辑 `lua\input_count.lua` 顶部的 `data_dir_override`，填绝对路径（Lua 字符串里 `\\` 要写两个），并把图表工具也放到该目录 |
| 图表工具 | 始终读写**自己所在的目录**（`%~dp0` / `$PSScriptRoot` / `__file__`），也可用命令行参数另指 |

三个数据文件（日汇总 / 分钟原始 / 当前分钟流水）必须放在**同一个目录**。

---

## 日常使用

| 想做什么 | 操作 |
| --- | --- |
| 看**折线图** | 双击数据目录里的 **`查看每日统计.bat`** → 自动生成并打开 `input_count_chart.html`，点顶部标签切换尺度 |
| 看**实时统计** | 中文状态依次输入 **`ii`** → 候选框显示「今日：xx字/xx键 \| 总计：…」→ `Esc` 关闭 |
| 看**演示图** | `python plot_input_count.py --demo --output demo_chart.html` |

### 三个图表标签

- **每日**：按天的字数/按键数折线（看长期趋势）。数据以 `input_count.txt` 的日汇总为准，**与 `ii` 弹窗完全一致**。
- **按天聚合**：由分钟级原始数据按天聚合，**组距可调**——下拉可选 1/2/3/7/14/30/90/180/365 天，
  也可直接输入 1–365 的任意天数（7 天=按周、30 天=按月）。横轴标每点起始日期，悬停看该组覆盖的日期范围。
- **按分钟聚合**：进入后默认按 1 分钟绘图并显示**最右侧（最近的数据）**，向左滚动看更早记录；
  **左右两侧纵轴刻度固定显示**（左轴=字、右轴=键）。横轴标注日期：日期画在每天 **0:00 数据点正下方**，
  时刻刻度按屏幕空间自动稀疏、任何组距都不重叠；滚动后看不到 0:00 时，当前日期固定显示在左下角。
  组距下拉可选 1/5/10/15/30/60/120/360/720/1440 分钟，也可输入 1–1440 的任意整数。
- 三个尺度共用同一套卡片汇总与明细表；鼠标悬停数据点看具体数值（空档显示「该时段无输入」）。
- 每次打开 / 切换标签 / 改组距后都自动定位到**最右侧（最新数据）**。

### 命令行参数

```text
python plot_input_count.py [--input FILE] [--raw FILE] [--output FILE] [--demo] [--png]
  --input    日汇总文件，默认 <脚本目录>\input_count.txt
  --raw      分钟级原始文件，默认 <脚本目录>\input_count_raw.txt（同基名 .tmp 会一并读取）
  --output   输出 HTML，默认 <脚本目录>\input_count_chart.html
  --demo     用合成示例数据出图（页面顶部有“演示图”横幅）
  --png      额外导出按日尺度 PNG（需要 matplotlib，可选）

powershell -NoProfile -ExecutionPolicy Bypass -File chart_powershell.ps1 `
  [-SummaryPath FILE] [-RawPath FILE] [-OutputPath FILE] [-Demo]
  参数含义与 Python 版一一对应；-Demo 不指定 -OutputPath 时会覆盖真实图表，务必指定。
```

---

## 数据文件格式

全部为 UTF-8 / ASCII 纯文本，位于数据目录：

| 文件 | 粒度 | 格式 |
| --- | --- | --- |
| `input_count.txt` | 日 | `start_iso=…` / `total_words=N total_keys=N` / `day=YYYYMMDD day_words=N day_keys=N` |
| `input_count_raw.txt` | **分钟** | `e=YYYYMMDDHHMM w=<字数> k=<按键数>`，**每分钟恰好一行**（append-only） |
| `input_count_raw.tmp` | 当前分钟流水 | 同上格式、逐条追加；跨分钟后聚合成一行写入上面的文件并清空 |

- **分钟级是原始数据**，按天/按分钟聚合都从它聚合而来，所以各档天然对齐。
- 每分钟的新增量先记到 `input_count_raw.tmp`（临时流水），**跨分钟时把整分钟聚合成一行**
  写进 `input_count_raw.txt` 再清空临时文件——主文件里每个时间戳只出现一次、不冗余。
- 打字时按键数按分钟累加；上屏字数在每次上屏时按分钟累加。触发键 `ii` 本身不计入按键统计。

### 统计口径（重要）

- **字数** = 每次上屏的字符数（中文/英文/标点都算）。
- **按键数** = 拼音字母键的累计（退格/空格/翻页/标点/西文模式不计）。
- **每日尺度 = `input_count.txt` 的 `day=` 行 = 与 `ii` 弹窗完全一致**。
- **按天聚合 / 按分钟聚合 = `input_count_raw.txt` 聚合**，只包含**开始记录分钟级之后**的输入；
  更早的输入不在这两个尺度里，所以启用当天两者的「今日」可能少于每日——往后每天都对齐。
- **隐私**：数据文件只记录「时间戳 + 字数 + 按键数」，不含任何输入内容。

---

## 目录结构

```text
Rime-input-count/
├── lua/
│   └── input_count.lua        # 统计核心（复制到 <Rime用户目录>\lua\）
├── rime.lua                   # 旧版 librime 备用入口（可选）
├── luna_pinyin_simp.custom.yaml  # 方案补丁示例（挂 lua_translator@*input_count）
├── plot_input_count.py        # 图表生成器（Python，主用，可选 --png）
├── chart_powershell.ps1       # 图表生成器（PowerShell 备用，同样三档）
├── 查看每日统计.bat             # 一键：优先 Python、否则 PowerShell，然后打开图表
├── sample_input_count.txt     # 示例数据（日汇总，纯合成）
├── sample_input_count_raw.txt # 示例数据（分钟级，纯合成，与上者逐日对齐）
├── install.ps1                # 一键安装脚本
├── CHANGELOG.md               # 更新日志
└── LICENSE                    # MIT
```

运行后数据目录还会出现（不入库，见 `.gitignore`）：

```text
input_count.txt / input_count_raw.txt / input_count_raw.tmp   # 你的真实统计数据
input_count_chart.html                                        # 图表输出（含真实数据与本机路径）
demo_chart.html                                               # 演示图输出
```

---

## 常见问题（万一不生效）

1. **打字没数据**：确认 Rime 用户目录（小狼毫注册表 `HKCU\SOFTWARE\Rime\Weasel\RimeUserDir`，
   默认 `%APPDATA%\Rime`）与 lua 自动定位的结果一致；数据目录是否存在、可写；
   右键托盘 →「重新部署」；必须**中文模式上屏**才计字数。
2. **`ii` 没反应**：重新部署；确认方案的 `engine/translators` 含 `lua_translator@*input_count`；
   极旧 librime 可把 `@*input_count` 改成 `@input_count`（并装好 `rime.lua` 绑定）。
3. **图表的聚合标签是空的**：说明 `input_count_raw.txt` 还没有数据——从安装起打字才会写分钟级；
   旧的只有日汇总。打几个字再刷新即可。
4. **改了 lua 想生效**：图表生成不用部署；但 **lua 逻辑改动需要重启 WeaselServer**
   （或重新部署）才会重新加载。
5. **中文乱码（PowerShell 生成的图）**：`chart_powershell.ps1` 必须保持 **UTF-8 带 BOM** 保存，
   否则 Windows PowerShell 5.1 会按系统 ANSI 代码页读脚本，界面文字全部乱码（这是踩过的坑）。
6. **手动重新部署**：托盘右键 →「重新部署」，或 `WeaselDeployer.exe /deploy`（工作目录=安装目录）。
7. **换机器 / 重装系统**：数据目录里三个 txt 文件就是全部记录，直接拷走继续用；
   重新跑一次 `install.ps1` 即可挂回新环境。

---

## 与上游 gist 的差异

核心统计思路来自 [ramonmi《Rime 输入统计》gist](https://gist.github.com/ramonmi/b1ac25bbe017c375b17fe23f0158d878)，
在其基础上做了以下修改（详见 `lua/input_count.lua` 头部注释）：

1. **数据路径可移植**：上游写死 Windows 绝对路径（`%APPDATA%` 在 Lua 里不展开）；
   本版用 `rime_api.get_user_data_dir()` 自动定位，另留 `data_dir_override` 手动覆盖。
2. **触发键 `sS` → `ii`**：朙月拼音的字母表只有小写，`S` 进不了输入码，`sS` 永远触发不了；
   `ii` 不是合法拼音，日常不会误触。
3. **退格不再虚增按键数**：并修复「触发→退格→再触发」重复回退按键的边界 bug。
4. **新增分钟级原始数据** `input_count_raw.txt`（tmp 流水 + 跨分钟聚合），供按天/按分钟图表聚合。
5. **新增整套 HTML 图表工具**：Python / PowerShell 双生成器、三档时间尺度交互图、一键入口 bat。

---

## 致谢与参考

- [ramonmi / Rime-input-count（gist）](https://gist.github.com/ramonmi/b1ac25bbe017c375b17fe23f0158d878) —— 原始统计思路与核心脚本
- [librime-lua Wiki · Scripting](https://github.com/hchunhui/librime-lua/wiki/Scripting) / [Objects](https://github.com/hchunhui/librime-lua/wiki/Objects) —— 模块写法与 `rime_api.get_user_data_dir()`
- [Rime 配置文件文档](https://rimeinn.github.io/rime/configuration.html) / [输入方案文档](https://rimeinn.github.io/rime/schema-design.html) —— 补丁与 `engine/translators` 挂载
- [rime/weasel issue #1812](https://github.com/rime/weasel/issues/1812) / [WeaselDeployer.cpp](https://github.com/rime/weasel/blob/master/WeaselDeployer/WeaselDeployer.cpp) —— 部署方式
- Lua 追加写文件 `io.open(path,"a")`：[TutorialsPoint](https://www.tutorialspoint.com/lua/lua_appending_to_files.htm)、[GameDev Academy](https://gamedevacademy.org/lua-file-i-o-tutorial-complete-guide)

## License

[MIT](LICENSE)

> 说明：核心统计逻辑源自 ramonmi 的 gist（原作未声明许可证），本仓库的修改、可移植化改造
> 与全部图表工具以 MIT 许可证发布。若你是原作者并对此有不同意见，欢迎提 issue 联系。
