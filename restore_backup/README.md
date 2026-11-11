# 小狼毫 · 输入统计 + 折线图（日 / 小时 / 分钟 三档可切换）

> **状态（2026-09-25）**：分钟级原始数据采集 + 三档时间尺度图表已完成。
> 用小狼毫打字即自动记录；图表页面顶部有 **每日 / 每小时 / 每分钟** 三个标签可切换。
> 验证报告见 `FINALIZE_RESULT.txt`、`SETUP_RESULT.txt`、`REDEPLOY_RESULT.txt`。

---

## 一、日常怎么用

| 想做什么 | 操作 |
| --- | --- |
| 看**折线图**（可切换日/小时/分钟） | 双击 **`查看每日统计.bat`** → 自动生成并打开 `input_count_chart.html`，点顶部标签切换尺度 |
| 看**实时统计** | 中文状态依次输入 **`ii`** → 候选框显示「今日：xx字/xx键 \| 总计：…」→ `Esc` 关闭 |
| 看**演示图**（合成示例数据） | 运行：`python plot_input_count.py --demo --output demo_chart.html` |

- **每日** 标签：按天的字数/按键数折线（看长期趋势）。
- **每小时** 标签：由分钟级原始数据按小时聚合（看一天内的作息分布）。
- **每分钟** 标签：可**左右滚动**查看更早的分钟级数据；顶部按钮可**调整密度**（每点覆盖 1/2/5/15/30/60 分钟）——点「1 分钟」最细、点「1 小时」最粗能看更长历史。
- 三个尺度共用同一套卡片汇总与明细表；鼠标悬停数据点看具体数值（空档显示「该时段无输入」）。

---

## 二、数据文件（自动写入本目录）

| 文件 | 粒度 | 格式 |
| --- | --- | --- |
| `input_count.txt` | 日 | `start_iso=…` / `total_words=N total_keys=N` / `day=YYYYMMDD day_words=N day_keys=N` |
| `input_count_raw.txt` | **分钟** | `e=YYYYMMDDHHMM w=<字数> k=<按键数>`，**每分钟恰好一行**（append-only） |
| `input_count_raw.tmp` | 当前分钟流水 | 同上格式、逐条追加；跨分钟后聚合成一行写入上面的文件并清空 |

- **分钟级是原始数据**，小时/日都是从它聚合出来的，所以三档天然对齐。
- 每分钟的新增量先记到 `input_count_raw.tmp`（临时流水），**跨分钟时把整分钟聚合成一行**写进 `input_count_raw.txt`，再清空临时文件。这样主文件里**每个时间戳只出现一次**、不冗余。
- 主文件是 append-only，写入开销恒定，数据量再大也不会越写越慢（见下）。
- 打字时按键数按分钟累加、上屏字数在每次上屏时按分钟累加。触发键 `ii` 本身不计入按键统计。

### 统计口径（重要，解释「弹窗 vs 图表」为何曾不一致）

- **字数** = 每次上屏的字符数（中文/英文/标点都算）。
- **按键数** = 拼音字母键的累计（退格/空格/翻页/标点/西文模式不计）。
- **每日尺度 = `input_count.txt` 的 `day=` 行 = 与 `ii` 弹窗完全一致**（弹窗读的就是这个值）。图表的「今日」卡片、每日折线、每日明细表都以它为准。
- **每小时 / 每分钟尺度 = `input_count_raw.txt` 聚合**。这是细粒度原始数据，但它**只从开始记录分钟级之后才有**；更早的输入（当天开始记录之前打的字）不体现在这两个尺度。所以「今天」这一天，小时/分钟加起来可能少于每日——这是数据记录起点造成的，往后每天都对齐。
- 历史 bug 已修：早先图表误用分钟级原始覆盖了每日汇总，导致「今日」显示得比弹窗少。现在**每日以汇总为准**，两边一致。

---

## 三、我已经装好的东西

| 文件 | 作用 |
| --- | --- |
| `lua/input_count.lua` | 统计核心（日汇总 + 分钟级原始） |
| `rime.lua` | librime-lua 入口（旧式写法备用） |
| `luna_pinyin_simp.custom.yaml` | 方案补丁：挂 `lua_translator@*input_count` |
| `plot_input_count.py` | 图表生成器（Python，日/小时/分钟三档 + 标签切换） |
| `chart_powershell.ps1` | 无 Python 时的备用生成器（同样三档输出） |
| `查看每日统计.bat` | 一键：优先 Python、否则 PowerShell，然后打开图表 |
| `input_count_chart.html` | 真实数据图表（含三档标签） |
| `demo_chart.html` | 合成示例数据演示图（同样三档） |
| `setup_and_verify.ps1` / `redeploy2.ps1` / `finalize.ps1` | 安装/部署/验证脚本 |

### 对上游 gist 的修改（原因）

1. 数据路径改为本机绝对路径（上游 `%APPDATA%` 在 Windows 不展开，必须改）。
2. 触发键 `sS` → `ii`（朙月拼音字母表只有小写，`S` 进不了输入码）。
3. 退格不再虚增按键数；修复「触发→退格→再触发」重复回退按键的边界 bug。
4. **新增** `input_count_raw.txt` 分钟级原始数据，供小时/分钟图表聚合。

---

## 四、万一不生效

1. **打字没数据**：确认小狼毫在用本目录（注册表 `HKCU\SOFTWARE\Rime\Weasel\RimeUserDir` 应为 `D:\MiniPrograms\RimeData`）；右键托盘→「重新部署」；必须中文模式上屏。
2. **`ii` 没反应**：重新部署；查 `build\luna_pinyin_simp.schema.yaml` 含 `lua_translator@*input_count`；极旧 librime 可把 `@*input_count` 改 `@input_count`。
3. **图表小时/分钟标签为空**：说明 `input_count_raw.txt` 还没数据——从本次更新起打字才会写分钟级；旧的只有日汇总。打几个字再刷新即可。
4. **改了 lua 想生效**：图表生成不用部署；但 **lua 逻辑改动需要重启 WeaselServer**（或重新部署）才会重新加载。
5. 手动重新部署：托盘右键→「重新部署」，或 `WeaselDeployer.exe /deploy`（工作目录=安装目录）。

---

## 五、来源

- 插件：[ramonmi 的 gist《Rime 输入统计》](https://gist.github.com/ramonmi/b1ac25bbe017c375b17fe23f0158d878)
- 模块写法：[librime-lua Wiki · Scripting](https://github.com/hchunhui/librime-lua/wiki/Scripting)
- Lua 追加写文件 `io.open(path,"a")`：[TutorialsPoint](https://www.tutorialspoint.com/lua/lua_appending_to_files.htm)、[GameDev Academy](https://gamedevacademy.org/lua-file-i-o-tutorial-complete-guide)
- 部署：[rime/weasel issue #1812](https://github.com/rime/weasel/issues/1812)、[WeaselDeployer.cpp](https://github.com/rime/weasel/blob/master/WeaselDeployer/WeaselDeployer.cpp)、[更新日志](https://rime.im/release/weasel)
