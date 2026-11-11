# AI 调试指引（交接文档：别再重新找工具/重新踩坑）

> 最后更新：2026-10-19。给以后接手本项目的 AI 用：调试要用的程序在哪、冒烟测试怎么跑、
> 需要临时下载的程序去哪下载（链接+代码都在），以及各功能代码的快速定位。

---

## 一、要改的文件在哪（改图表界面改「生成器」，别改生成出来的 HTML）

| 文件 | 说明 |
| --- | --- |
| `plot_input_count.py` | **主生成器（Python）**：样式在 `CSS` 常量、页面 JS 在 `CHART_JS` 常量、页面骨架在 `build_html()` |
| `chart_powershell.ps1` | **备用生成器（PowerShell）**：`$CSS` / `$CHART_JS` here-string + 后半段 HTML 拼装。**必须与 Python 版同步改**（两份 CSS/JS 一字不差） |
| `input_count_chart.html` | **生成物**（两个生成器的输出），绝不手改；改完生成器重新生成即可 |
| `_smoke2.js` | Node 冒烟/回归测试（DOM 桩，不需浏览器）。改了 CSS/JS/HTML 结构就往里加检查 |
| `_smoke_lua.py` | `lua\keylog.lua` 的回归测试（跑在真实 rime.dll 的 Lua 里）。没改 lua 不用跑 |
| `keylog_helper.py` | 按键明细本机小服务（127.0.0.1:47321），图表单击/双击功能的后端 |

⚠️ **大坑：`chart_powershell.ps1` 必须带 UTF-8 BOM。** 没有 BOM 时 Windows PowerShell 5.1 按 GBK
读它，中文全乱码、脚本直接解析失败。很多编辑器保存时会把 BOM 去掉——**每次编辑完检查前 3 字节
是 `EF BB BF`**，不是就补上：

```powershell
$p = 'chart_powershell.ps1'
$t = [System.IO.File]::ReadAllText($p, [System.Text.UTF8Encoding]::new($false))
[System.IO.File]::WriteAllText($p, $t, [System.Text.UTF8Encoding]::new($true))
```

---

## 二、调试用的程序在哪（本机已装好，直接用，不用找）

| 程序 | 路径 | 用途 |
| --- | --- | --- |
| Python 3.11.7 | `D:\MiniPrograms\Python3117\python.exe` | 生成图表、跑 `keylog_helper.py`、`_smoke_lua.py` |
| Node.js v22.22.2 | `D:\MiniPrograms\nodejs\node.exe` | 跑 `_smoke2.js` 冒烟测试 |
| Windows PowerShell 5.1 | `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe` | 跑备用生成器 `chart_powershell.ps1` |
| rime.dll（内嵌 Lua 解释器） | `C:\Program Files\Rime\weasel-0.17.4\rime.dll` | `_smoke_lua.py` 用它的 Lua C API 执行 keylog.lua |
| 小狼毫用户目录 | `D:\MiniPrograms\RimeData` | Rime 挂载点：`lua\input_count.lua`、`lua\keylog.lua`、`rime.lua`、`luna_pinyin_simp.custom.yaml` |

其他：按键明细小服务端口 **47321**（只听 127.0.0.1）；数据文件 `input_count.txt`（日汇总）、
`input_count_raw.txt`（分钟级原始）、`keylog\`（按键明细）、`keylog_ts\`（按键时间戳）都在本目录。

---

## 三、冒烟测试怎么跑（改完生成器必跑，全 PASS 才算完）

```powershell
cd D:\MiniPrograms\RimeData\Rime-input-count
# ① Python 生成器产物
& D:\MiniPrograms\Python3117\python.exe plot_input_count.py
& D:\MiniPrograms\nodejs\node.exe _smoke2.js input_count_chart.html
# ② PowerShell 备用生成器产物（验证两生成器同步）
powershell -NoProfile -ExecutionPolicy Bypass -File chart_powershell.ps1 -OutputPath _ps_check.html
& D:\MiniPrograms\nodejs\node.exe _smoke2.js _ps_check.html
del _ps_check.html
```

- 期望：全部 `PASS`、最后一行 `done`、退出码 0（任何 `FAIL` 都会置退出码 1）。
- 改了 `lua\keylog.lua` 才需要另外跑：`& D:\MiniPrograms\Python3117\python.exe _smoke_lua.py`。
- 测试是 DOM 桩模拟（`_smoke2.js` 内置 `document`/`window` 桩），**不需要下载浏览器**；
  想看真实观感就双击 `查看每日统计.bat` 打开页面人工看一眼。

---

## 四、冒烟测试用的临时程序：下载链接 + 代码（工具缺失时照抄重新下载）

**本次（2026-10-19）调试没有临时下载任何程序**——Node、Python 都是本机常驻（见上表）。
若哪天机器上没有这些工具、需要临时下载来跑冒烟测试，用下面的**官方链接 + 代码**
（下载到 `%TEMP%` 即可，测完可整个删掉；请把实际用到的链接/代码继续补在这节里）：

### 1. Node.js（跑 `_smoke2.js` 必需）— 官方免安装 zip

- 下载链接：<https://nodejs.org/dist/v22.22.2/node-v22.22.2-win-x64.zip>
  （全部版本目录：<https://nodejs.org/dist/> ；现装版本 v22.22.2）

```powershell
Invoke-WebRequest -Uri 'https://nodejs.org/dist/v22.22.2/node-v22.22.2-win-x64.zip' -OutFile "$env:TEMP\node.zip"
Expand-Archive "$env:TEMP\node.zip" -DestinationPath "$env:TEMP\nodejs" -Force
& "$env:TEMP\nodejs\node-v22.22.2-win-x64\node.exe" -v
# 直接拿它跑冒烟测试：
& "$env:TEMP\nodejs\node-v22.22.2-win-x64\node.exe" _smoke2.js input_count_chart.html
```

### 2. Python 3.11.7（生成图表 / 跑 `_smoke_lua.py`）— 官方 embeddable 免安装包

- 下载链接（免安装 zip）：<https://www.python.org/ftp/python/3.11.7/python-3.11.7-embed-amd64.zip>
- 下载链接（正式安装器，现装版就是它装的）：<https://www.python.org/ftp/python/3.11.7/python-3.11.7-amd64.exe>

```powershell
Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.7/python-3.11.7-embed-amd64.zip' -OutFile "$env:TEMP\py.zip"
Expand-Archive "$env:TEMP\py.zip" -DestinationPath "$env:TEMP\py311" -Force
& "$env:TEMP\py311\python.exe" plot_input_count.py     # embeddable 包无 pip，但标准库够本项目用
```

### 3. rime.dll（仅 `_smoke_lua.py` 需要）— 小狼毫安装自带，不用单独下载

- 路径见上表（随小狼毫 0.17.4 安装）。万一小狼毫重装/换版本：官方下载页 <https://rime.im/download/>
  （装完把 `RIME_DLL` 路径改到新版本目录即可，见 `_smoke_lua.py` 开头）。

---

## 五、各功能代码快速定位（改哪搜哪个词）

| 要改的东西 | 位置 |
| --- | --- |
| 「隐藏 x 及以下的[上屏字数/按键次数]」短语 | `build_html()` 里搜 `thr-btn` / `dThMetric` / `minThMetric`（PowerShell 版搜同名 id） |
| 指标按钮切换逻辑 | `CHART_JS` 里 `metricOf` / `bindMetric` |
| 隐藏过滤逻辑（按所选指标） | `renderChart` 里搜 `pts[i][midx] > th` |
| 滚轮步长（相邻数值差+1、滚一次至少隐藏/显示一个数据） | `wheelTh` + `bindThWheel`；「当前最小显示值/最大隐藏值」就在这两个函数里 |
| 阈值上下箭头（±1 精细调节，刻意保留） | 原生 number input 的 spinner（CSS `.thr-in::-webkit-inner-spin-button`），别动 |
| 按键明细面板右下角手柄斜线 | CSS `.klpanel-rz`（`linear-gradient(135deg, ...)` = 斜线顺时针转 90° 后的方向） |
| 滚动条不被手柄遮挡 | CSS `.klpanel-bd` 的 `margin-bottom: 18px`（滚动条整体位于手柄上方） |
| 重复渲染短路（性能） | `renderChart` 开头的 `LASTSIG` 签名——**新增任何影响渲染的参数（如指标）务必加进签名**，否则切参数不重绘 |
| 悬停提示框 | `CHART_JS` 里 `show`/`move`（`#tt`） |
| 单击看按键 / 双击开副本 | `klShowKeys` / `klOpenCopy` + `keylog_helper.py` 的 `/keys`、`/open` |

## 六、老坑备忘

1. `chart_powershell.ps1` 的 UTF-BOM（见第一节）——最常踩。
2. 两个生成器的 `$CSS`/`$CHART_JS` 与 `CSS`/`CHART_JS` 必须**逐字同步**，改一处就要改另一处。
3. `_smoke2.js` 的 DOM 桩是极简实现：JS 里用到新的 DOM API（如 `document.activeElement`）时，
   记得在测试桩里补上，否则测试会假失败/假通过。
4. 图表数据来自 `input_count_raw.txt` + `input_count_raw.tmp`（当前分钟流水），两者都要读。
