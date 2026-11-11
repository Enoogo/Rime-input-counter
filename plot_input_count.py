#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""plot_input_count.py - 生成 Rime（小狼毫）输入统计折线图（可切换 按天聚合/按分钟聚合 尺度）。

数据源::

    input_count.txt        日汇总（权威）：start_iso / total_* / day=YYYYMMDD day_words=N day_keys=N
    input_count_raw.txt    分钟级原始：e=YYYYMMDDHHMM w=<字数> k=<按键数>
    keylog\YYYYMMDD.txt    按键明细（每天一个）：每个有按键的分钟一行「行首 HHMM + 依次按下的键」
                           图表页单击数据点显示该点按过的键、双击生成 txt 副本并用默认程序打开
                           （副本自动删掉对应行之前的内容 = 首行即对应行；由 keylog_helper.py 执行）

尺度口径：
  * 卡片汇总与每日明细表 —— 以 input_count.txt 的 day= 行为准（与 ii 弹窗显示的数字完全一致）。
  * 按天聚合/按分钟聚合 —— 由 input_count_raw.txt 聚合（细粒度，但只含开始记录分钟级之后的数据）。
    组距均可在页面上输入：分钟 1–1440、天 1–365。按天聚合组距设为 1 天时完全覆盖原「每日」图表，
    因此「每日」标签已删除。

页面交互要点（细节见 CHART_JS 里的注释与 README.md「2026-10-24 更新」）：
  * 「隐藏 [m] 及以下的 [上屏字数/按键次数]」的 m 按指标分别记住（每个面板各一份，切换互不覆盖）。
  * 纵轴最大值可点着改：点某档刻度数字 -> 它成为该轴最大值；点最顶上那个 -> 减半；
    字、键各自独立，折线图与直方图都支持；改组距/改阈值/换指标后回到自动算法。
  * 直方图的悬停提示只在柱子上出现（柱间空白不响应）。
  * 按天聚合的数据点单击也能看该天的按键明细（与按分钟聚合同一套提示框与面板）。

用法::

    python plot_input_count.py                     # -> input_count_chart.html
    python plot_input_count.py --png               # 可选 PNG（需 matplotlib，按日尺度）
"""

import argparse
import calendar
import datetime
import html
import json
import math
import os
import re
import subprocess
import sys
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SUMMARY = os.path.join(BASE_DIR, "input_count.txt")
DEFAULT_RAW = os.path.join(BASE_DIR, "input_count_raw.txt")
DEFAULT_OUTPUT = os.path.join(BASE_DIR, "input_count_chart.html")
KEYLOG_HELPER = os.path.join(BASE_DIR, "keylog_helper.py")
KEYLOG_HELPER_PORT = 47321

DAY_RE = re.compile(r"^\s*day=(\d{8})\s+day_words=(-?\d+)\s+day_keys=(-?\d+)\s*$")
TOTAL_RE = re.compile(r"^\s*total_words=(-?\d+)\s+total_keys=(-?\d+)\s*$")
START_RE = re.compile(r"^\s*start_iso=(\S.*)$")
RAW_RE = re.compile(r"^\s*e=(\d{12})\s+w=(-?\d+)\s+k=(-?\d+)\s*$")

# 全页主题色唯一来源：上屏字数=蓝、按键次数=橙。
# CSS / 页面 JS / 静态兜底 SVG 里一律写占位符 __CW__ / __CK__，build_html() 末尾统一替换；
# 想换配色只改这两行。
COLOR_WORDS = "#2563eb"
COLOR_KEYS = "#f59e0b"

# 仅限制「无 JS 时静态兜底 SVG」的最长点数；页面实际图表由 JS 绘制，画出全部数据点
MAX_POINTS = {"day": 365, "minute": 300}


def fmt(n):
    try:
        return "{:,}".format(int(n))
    except (TypeError, ValueError):
        return str(n)


def ensure_keylog_helper():
    """启动按键明细小服务 keylog_helper.py（幂等：已在跑就跳过）。

    图表页「单击显示按键 / 双击开副本」通过 http://127.0.0.1 调用它执行。
    查看每日统计.bat 也会启动一次；这里兜底，直接运行本脚本时功能同样可用。
    """
    if not os.path.isfile(KEYLOG_HELPER):
        return
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:%d/ping" % KEYLOG_HELPER_PORT, timeout=0.6
        ) as resp:
            if resp.status == 200:
                return          # 已经在跑
    except Exception:
        pass
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = pythonw if os.path.isfile(pythonw) else sys.executable
    try:
        subprocess.Popen(
            [exe, KEYLOG_HELPER],
            cwd=BASE_DIR,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, ValueError) as exc:
        print("WARN: cannot start keylog helper: %s" % exc)


def nice_max(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 10
    if value <= 0:
        return 10
    exp = int(math.floor(math.log10(value)))
    base = 10 ** exp
    for mult in (1, 2, 5, 10):
        if value <= mult * base:
            return mult * base
    return 10 * base


def parse_summary(path):
    if not os.path.isfile(path):
        return None
    info = {"start_iso": "", "total_words": 0, "total_keys": 0, "days": {}}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                m = DAY_RE.match(line)
                if m:
                    info["days"][m.group(1)] = (int(m.group(2)), int(m.group(3)))
                    continue
                m = TOTAL_RE.match(line)
                if m:
                    info["total_words"] = int(m.group(1))
                    info["total_keys"] = int(m.group(2))
                    continue
                m = START_RE.match(line)
                if m and not info["start_iso"]:
                    info["start_iso"] = m.group(1).strip()
    except OSError as exc:
        print("WARN: cannot read %s: %s" % (path, exc))
        return None
    return info


def raw_dir_of(path):
    """分钟级数据文件夹：input_count_raw.txt -> input_count_raw（不带扩展名的同名文件夹）。"""
    return os.path.splitext(path)[0]


def raw_sources(path):
    """分钟级数据的全部来源（按时间顺序）：

    1. ``input_count_raw\\YYYYMM.txt`` —— 新版：**每月一个文件**（2026-10-24 起），文件名即年月；
    2. ``input_count_raw.txt``        —— 旧版单文件（还没迁移、或还没换用新 lua 时仍有新数据写进去）；
    3. ``input_count_raw.tmp``        —— 当前这一分钟的流水（由 lua 写入，跨分钟后并入月度文件）。

    旧版文件存在时一并读取，所以「先换生成器、后换 lua」或「先换 lua、后迁移」都不会丢数据。
    """
    out = []
    folder = raw_dir_of(path)
    if os.path.isdir(folder):
        try:
            names = sorted(n for n in os.listdir(folder) if n.lower().endswith(".txt"))
        except OSError as exc:
            print("WARN: cannot list %s: %s" % (folder, exc))
            names = []
        out.extend(os.path.join(folder, n) for n in names)
    if os.path.isfile(path):
        out.append(path)
    tmp_path = os.path.splitext(path)[0] + ".tmp"
    if os.path.isfile(tmp_path):
        out.append(tmp_path)
    return out


def parse_raw(path):
    """解析分钟级原始数据（见 raw_sources：按月文件 + 旧单文件 + 当前分钟流水）。
    返回 {minutekey: (w, k)}（同分钟求和）。"""
    minutes = {}
    for src in raw_sources(path):
        try:
            with open(src, "r", encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    m = RAW_RE.match(raw.strip())
                    if not m:
                        continue
                    key = m.group(1)
                    w = int(m.group(2))
                    k = int(m.group(3))
                    if key in minutes:
                        minutes[key] = (minutes[key][0] + w, minutes[key][1] + k)
                    else:
                        minutes[key] = (w, k)
        except OSError as exc:
            print("WARN: cannot read %s: %s" % (src, exc))
    return minutes


def migrate_legacy_raw(path):
    """一次性迁移：把旧版单文件 ``input_count_raw.txt`` 按月拆进 ``input_count_raw\\YYYYMM.txt``。

    只在「旧文件里有 e= 行」且「按月文件夹还不存在」时执行（即升级后第一次运行），
    旧文件改名为 ``input_count_raw.txt.bak`` 留底，绝不删数据。返回是否做了迁移。
    """
    folder = raw_dir_of(path)
    if not os.path.isfile(path) or os.path.isdir(folder):
        return False
    by_month = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                m = RAW_RE.match(line)
                if not m:
                    continue
                by_month.setdefault(m.group(1)[:6], []).append(line)
    except OSError as exc:
        print("WARN: cannot read %s: %s" % (path, exc))
        return False
    if not by_month:
        return False
    try:
        os.makedirs(folder, exist_ok=True)
        for month in sorted(by_month):
            with open(os.path.join(folder, month + ".txt"), "w",
                      encoding="utf-8", newline="\n") as fh:
                fh.write("\n".join(by_month[month]) + "\n")
        os.replace(path, path + ".bak")
    except OSError as exc:
        print("WARN: cannot migrate %s: %s" % (path, exc))
        return False
    print("NOTE: 分钟级数据已按月拆分：%s -> %s（旧文件保留为 %s.bak，共 %d 个月）"
          % (path, folder, path, len(by_month)))
    return True


def aggregate(minutes, width):
    acc = {}
    for key, (w, k) in minutes.items():
        b = key[:width]
        if b in acc:
            acc[b] = (acc[b][0] + w, acc[b][1] + k)
        else:
            acc[b] = (w, k)
    return acc


_STEP = {
    "minute": datetime.timedelta(minutes=1),
    "day": datetime.timedelta(days=1),
}
_FMT = {
    "minute": "%Y%m%d%H%M",
    "day": "%Y%m%d",
}


def continuous(observed, scale, max_points):
    """把有数据的时间桶补成连续时间轴：缺口补 (0,0)。

    只在渲染图表时补零，让横轴照常显示没打字的时段；数据文件不写这些 0 行。
    至多返回 max_points 个点（取最近的一段）。
    """
    if not observed:
        return []
    fmt = _FMT[scale]
    step = _STEP[scale]
    keys = sorted(observed)
    last = datetime.datetime.strptime(keys[-1], fmt)
    first = datetime.datetime.strptime(keys[0], fmt)
    earliest = last - step * (max_points - 1)
    start = first if first > earliest else earliest
    out = []
    cur = start
    while cur <= last:
        k = cur.strftime(fmt)
        w, kk = observed.get(k, (0, 0))
        out.append((k, w, kk))
        cur = cur + step
    return out


# 横轴短标签
def lab_day(key):
    return "%s-%s" % (key[4:6], key[6:8])


def lab_minute(key):
    return "%s:%s" % (key[8:10], key[10:12])


# 悬停用完整时间
def time_day(key):
    return "%s-%s-%s" % (key[0:4], key[4:6], key[6:8])


def time_minute(key):
    return "%s-%s-%s %s:%s" % (key[0:4], key[4:6], key[6:8], key[8:10], key[10:12])


def date_minute(key):
    """按分钟聚合日期标注：只在每天 0:00 的数据点返回日期（标在该点正下方，覆盖此点以右当天的数据）。"""
    if key[8:12] != "0000":
        return ""
    return "%s-%s-%s" % (key[0:4], key[4:6], key[6:8])


def text_width(s, px=11.0):
    """粗略估算 11px 文本宽度（ASCII 约 0.62em、CJK 约 1em），供横轴刻度防重叠使用。"""
    w = 0.0
    for ch in s:
        w += px if ord(ch) > 0x2E80 else px * 0.62
    return w


def label_stride(labels, dx, gap=12.0):
    """横轴刻度步长：保证相邻标签中心距 >= 最大标签宽 + gap，任何组距/点数都不重叠。"""
    if not labels:
        return 1
    max_w = max(text_width(s) for s in labels)
    if dx <= 0:
        return len(labels)
    return max(1, int(math.ceil((max_w + gap) / dx)))


def build_svg(points, label_fn, time_fn, date_fn=None):
    """双纵轴折线图 SVG。points: [(key, w, k)]。含可视点 + 悬停命中区（JS 提示框）。

    date_fn 可选：返回非空字符串的点视为「新的一天 0:00」，在其正下方标注日期
    （该日期覆盖此点以右的数据），并画一条浅色日分隔线。
    横轴时刻刻度按实际文本宽度自动定步长，任何组距都绝不重叠。
    """
    n = len(points)
    width, height = 1000, 430
    ml, mr, mt, mb = 78, 78, 58, 64
    pw = width - ml - mr
    ph = height - mt - mb
    wmax = nice_max(max([p[1] for p in points] or [0]))
    kmax = nice_max(max([p[2] for p in points] or [0]))

    def x_at(i):
        return ml + (pw * 0.5 if n <= 1 else pw * float(i) / (n - 1))

    def y_at(v, vmax):
        return mt + ph * (1.0 - float(v) / vmax)

    out = []
    out.append(
        '<svg class="chart" viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" '
        'preserveAspectRatio="xMidYMid meet">' % (width, height)
    )

    steps = 5
    for s in range(steps + 1):
        frac = s / float(steps)
        y = mt + ph * (1.0 - frac)
        out.append(
            '<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#e5e7eb" stroke-width="1"/>'
            % (ml, y, ml + pw, y)
        )
        out.append(
            '<text x="%d" y="%.1f" class="yl yl-left" text-anchor="end">%s</text>'
            % (ml - 10, y + 4, fmt(wmax * frac))
        )
        out.append(
            '<text x="%d" y="%.1f" class="yl yl-right" text-anchor="start">%s</text>'
            % (ml + pw + 10, y + 4, fmt(kmax * frac))
        )

    out.append(
        '<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#9ca3af" stroke-width="1.2"/>'
        % (ml, mt + ph, ml + pw, mt + ph)
    )

    y_time = mt + ph + 22
    y_date = mt + ph + 42

    # 日分隔线 + 日期标注（每天 0:00 的数据点正下方）
    # 防重叠：相邻日期文字的边界之间至少留 8px，放不下就跳过（组距很大时每个点都是 0:00）。
    if date_fn:
        last_right = None
        for i, (key, w, k) in enumerate(points):
            dlab = date_fn(key)
            if not dlab:
                continue
            x = x_at(i)
            out.append(
                '<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#d1d5db" '
                'stroke-width="1" stroke-dasharray="3 4"/>' % (x, mt, x, mt + ph)
            )
            half = text_width(dlab) / 2.0
            if last_right is None or (x - half) >= last_right + 8:
                out.append(
                    '<text x="%.1f" y="%d" class="xl xd" text-anchor="middle">%s</text>'
                    % (x, y_date, html.escape(dlab))
                )
                last_right = x + half

    # 时刻刻度：按文本宽度定步长，任何组距都不重叠
    labels = [label_fn(p[0]) for p in points]
    dx = (pw / float(n - 1)) if n > 1 else float(pw)
    stride = label_stride(labels, dx)
    for i in range(0, n, stride):
        x = x_at(i)
        out.append(
            '<text x="%.1f" y="%d" class="xl" text-anchor="middle">%s</text>'
            % (x, y_time, html.escape(labels[i]))
        )

    kpts = " ".join("%.1f,%.1f" % (x_at(i), y_at(points[i][2], kmax)) for i in range(n))
    wpts = " ".join("%.1f,%.1f" % (x_at(i), y_at(points[i][1], wmax)) for i in range(n))
    out.append(
        '<polyline points="%s" fill="none" stroke="%s" stroke-width="2" '
        'stroke-linejoin="round"/>' % (kpts, COLOR_KEYS)
    )
    out.append(
        '<polyline points="%s" fill="none" stroke="%s" stroke-width="2.5" '
        'stroke-linejoin="round"/>' % (wpts, COLOR_WORDS)
    )

    # 可视数据点
    for i, (key, w, k) in enumerate(points):
        x = x_at(i)
        out.append(
            '<circle cx="%.1f" cy="%.1f" r="3.2" fill="%s"/>'
            % (x, y_at(k, kmax), COLOR_KEYS)
        )
        out.append(
            '<circle cx="%.1f" cy="%.1f" r="3.2" fill="%s"/>'
            % (x, y_at(w, wmax), COLOR_WORDS)
        )

    # 悬停命中区（透明大圆，带数据，供 JS 提示框显示）
    for i, (key, w, k) in enumerate(points):
        x = x_at(i)
        tip_t = html.escape(time_fn(key), quote=True)
        attrs = 'data-label="%s" data-w="%s" data-k="%s"' % (tip_t, fmt(w), fmt(k))
        out.append(
            '<circle class="hit" cx="%.1f" cy="%.1f" r="14" %s/>'
            % (x, y_at(w, wmax), attrs)
        )
        out.append(
            '<circle class="hit" cx="%.1f" cy="%.1f" r="14" %s/>'
            % (x, y_at(k, kmax), attrs)
        )

    out.append(
        '<line x1="%d" y1="24" x2="%d" y2="24" stroke="%s" stroke-width="3"/>'
        % (ml, ml + 28, COLOR_WORDS)
    )
    out.append('<text x="%d" y="29" class="legend">上屏字数</text>' % (ml + 36))
    out.append(
        '<line x1="%d" y1="24" x2="%d" y2="24" stroke="%s" stroke-width="3"/>'
        % (ml + 190, ml + 218, COLOR_KEYS)
    )
    out.append('<text x="%d" y="29" class="legend">按键数</text>' % (ml + 226))

    out.append(
        '<text x="%d" y="%d" class="axis-title" text-anchor="middle">字</text>'
        % (ml - 44, mt - 12)
    )
    out.append(
        '<text x="%d" y="%d" class="axis-title" text-anchor="middle">键</text>'
        % (ml + pw + 46, mt - 12)
    )

    out.append("</svg>")
    return "\n".join(out)


CSS = """
* { box-sizing: border-box; }
body { margin: 0; background: #f3f4f6; color: #111827;
  font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif; }
.wrap { max-width: 1080px; margin: 0 auto; padding: 26px 16px 56px; }
h1 { font-size: 22px; margin: 0 0 6px; }
.sub { color: #6b7280; font-size: 13px; margin-bottom: 18px; }
.cards { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 18px; }
.card { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px;
  padding: 12px 16px; min-width: 150px; flex: 1 1 150px; }
.card .k { font-size: 12px; color: #6b7280; }
.card .v { font-size: 20px; font-weight: 600; margin-top: 4px; }
.card .v small { font-size: 12px; font-weight: 400; color: #6b7280; }
.panel { background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 14px 16px; }
svg.chart { width: 100%; height: auto; display: block; background: #fff; border-radius: 8px; }
svg.chart text { font-family: "Segoe UI", "Microsoft YaHei", sans-serif; }
.yl { font-size: 11px; fill: #6b7280; }
.yl-left { fill: __CW__; }
.yl-right { fill: #d97706; }
.xl { font-size: 11px; fill: #6b7280; }
.xd { fill: #4b5563; font-weight: 600; }
.legend { font-size: 13px; fill: #374151; }
.axis-title { font-size: 12px; fill: #9ca3af; }
details { margin-top: 14px; }
summary { cursor: pointer; color: __CW__; font-size: 14px; }
table { border-collapse: collapse; width: 100%; margin-top: 10px; font-size: 13px; }
th, td { border: 1px solid #e5e7eb; padding: 6px 10px; text-align: right; }
th:first-child, td:first-child { text-align: left; }
tr:nth-child(even) td { background: #f9fafb; }
.empty { text-align: center; padding: 44px 16px; color: #6b7280; line-height: 1.9; }
.empty strong { color: #111827; font-size: 16px; }
.banner { background: #fef3c7; border: 1px solid #fcd34d; color: #92400e;
  padding: 10px 14px; border-radius: 8px; margin-bottom: 14px;
  font-size: 14px; text-align: center; }
code { background: #eef2ff; padding: 1px 6px; border-radius: 4px; font-size: 12px; }
.foot { color: #9ca3af; font-size: 12px; margin-top: 16px; line-height: 1.8; }
.tabs input[type=radio] { position: absolute; opacity: 0; pointer-events: none; }
/* 「按天聚合 / 按分钟聚合」= 两个挨在一起的标签页：都白底、只有左上/右上圆角；
   选中的那个压住下面白卡片的顶边（连成一体），没选中的露出底边 = 落在后面。 */
.tabbar { display: flex; align-items: flex-end; gap: 0; margin: 0 0 -1px; padding: 0;
  position: relative; z-index: 3; }
.tabbar label { cursor: pointer; padding: 8px 22px; margin: 0; background: #fff;
  color: #9ca3af; border: 1px solid #e5e7eb; border-bottom: 1px solid #e5e7eb;
  border-radius: 0; font-size: 13px; position: relative;
  box-shadow: inset 0 -6px 8px -8px rgba(0,0,0,0.18); }
.tabbar label:first-child { border-radius: 8px 0 0 0; }
.tabbar label:last-child { border-radius: 0 8px 0 0; }
#s-dagg:checked ~ .tabbar label[for="s-dagg"],
#s-min:checked ~ .tabbar label[for="s-min"] {
  color: #111827; border-bottom-color: #fff; z-index: 2; box-shadow: none; }
.pane { display: none; }
#s-dagg:checked ~ .pane-dagg,
#s-min:checked ~ .pane-min { display: block; }
/* 折线图整块白卡片：组距那一行 + 图表都在它里面；顶边被选中的标签页压住 1px */
.chartcard { background: #fff; border: 1px solid #e5e7eb; border-radius: 0 8px 8px 8px;
  padding: 12px 14px 8px; position: relative; z-index: 1; }
circle.hit { fill: rgba(0,0,0,0); pointer-events: all; cursor: pointer; }
rect.hhit { fill: rgba(0,0,0,0); pointer-events: all; cursor: pointer; }
.minctl { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.minctl .minctl-label { font-size: 13px; color: #6b7280; }
.bm-input { width: 88px; padding: 6px 8px; border: 1px solid #e5e7eb; border-radius: 6px;
  font-size: 13px; color: #111827; background: #fff; }
.bm-input:focus { outline: none; border-color: __CW__; }
.bkt { cursor: pointer; padding: 6px 14px; border: 1px solid __CW__; border-radius: 6px;
  background: __CW__; color: #fff; font-size: 12px; }
.bkt:hover { background: #1d4ed8; }
.minctl-hint { font-size: 12px; color: #b45309; }
.minwrap { position: relative; }
.scroll { overflow-x: auto; overflow-y: hidden; border: 1px solid #f1f5f9; border-radius: 8px;
  background: #fff; padding-bottom: 6px; }
/* 固定的纵轴刻度（纯白底，四角与图表白色矩形一致） */
.yax { position: absolute; top: 0; width: 78px; height: 431px; pointer-events: none;
  background: #fff; border-radius: 8px; }
.yax-l { left: 0; }
.yax-r { right: 0; }
.yax .yt { position: absolute; transform: translateY(-50%); font-size: 11px;
  font-variant-numeric: tabular-nums; white-space: nowrap; }
.yax-l .yt { right: 10px; text-align: right; }
.yax-r .yt { left: 10px; }
/* 纵轴刻度数字可点：点一下把该数值设为该轴的纵轴最大值（再点最大那个就减半） */
.yax .ytc { pointer-events: auto; cursor: pointer; }
/* 直方图的纵轴刻度数字（画在 SVG 里，pointer-events: all = 整个文字框都可点） */
.hyt { pointer-events: all; cursor: pointer; }
.yt-l { color: __CW__; }
.yt-r { color: #d97706; }
.yt-title { font-size: 12px; color: #9ca3af; }
/* 滚动后看不到 0:00 时，固定在左下角（左侧纵轴下方）的日期 */
.datefix { position: absolute; left: 3px; top: 412px; z-index: 4; display: none;
  background: #fff; border: 1px solid #d1d5db; border-radius: 6px; padding: 1px 6px;
  font-size: 11px; font-weight: 600; color: #374151; white-space: nowrap;
  font-variant-numeric: tabular-nums; pointer-events: none;
  box-shadow: 0 1px 3px rgba(0,0,0,0.10); }
#minsvg, #dagsvg { display: block; }
.chk { display: flex; align-items: center; gap: 7px; font-size: 13px; color: #374151;
  margin-top: 8px; cursor: pointer; user-select: none; }
/* 「平均线」「星期底色」「隐藏 … 及以下的 …」同一行 */
.opts { display: flex; align-items: center; gap: 20px; flex-wrap: wrap; margin-top: 8px;
  font-size: 13px; color: #374151; }
.opts .chk { margin-top: 0; }
/* 峰值时间（最高字数/最高键数）做成可点链接：点击把折线图滚到对应数据点 */
.pk { color: inherit; text-decoration: underline; text-underline-offset: 2px; cursor: pointer; }
.pk:hover { color: #111827; }
.chk input[type=checkbox] { width: 15px; height: 15px; accent-color: __CW__; cursor: pointer; }
.avgv { font-weight: 600; }
/* 「隐藏[0]及以下的[上屏字数]」：数字输入框与指标按钮自然嵌进短语里（紧贴两侧文字、无割裂感） */
.thr { gap: 0; cursor: default; }
.thr .thr-in { width: 52px; height: 22px; margin: 0 4px; padding: 0 2px;
  border: 1px solid #e5e7eb; border-radius: 5px; background: #fff;
  font-size: 13px; color: #111827; text-align: center; font-variant-numeric: tabular-nums; }
.thr .thr-in:focus { outline: none; border-color: __CW__; }
.thr .thr-in::-webkit-inner-spin-button { opacity: 0; }
.thr .thr-in:hover::-webkit-inner-spin-button,
.thr .thr-in:focus::-webkit-inner-spin-button { opacity: 1; }
/* 「隐藏[x]及以下的[上屏字数]」尾部的指标切换：就是短语里的普通文字，只是颜色随所选指标走
   （上屏字数=__CW__、按键次数=__CK__，与图表线条同色），无边框、无底色、字号与前后文字完全一致。 */
.thr .thr-btn { margin: 0; padding: 0; border: 0; background: none; font: inherit;
  color: __CW__; cursor: pointer; }
.thr .thr-btn[data-metric="keys"] { color: __CK__; }
.thr .thr-btn:focus-visible { outline: 1px dotted currentColor; }
.tooltip { position: fixed; z-index: 100; display: none; background: #1f2937; color: #f9fafb;
  padding: 10px 12px; border-radius: 8px; font-size: 13px; line-height: 1.7;
  box-shadow: 0 6px 20px rgba(0,0,0,0.28); pointer-events: none; white-space: nowrap; }
.tooltip .tt-time { font-weight: 600; color: #fff; margin-bottom: 4px; }
.tooltip .tt-row { display: flex; align-items: center; gap: 7px; }
.tooltip .tt-sw, .tooltip .tt-sk { width: 11px; height: 11px; border-radius: 3px; display: inline-block; }
.tooltip .tt-sw { background: __CW__; }
.tooltip .tt-sk { background: __CK__; }
.tooltip .tt-row b { margin-left: auto; padding-left: 16px; font-variant-numeric: tabular-nums; }
.tooltip .tt-empty { color: #9ca3af; font-size: 12px; margin-top: 4px; }
/* 按键明细面板：单击数据点后在右侧宽大面板里显示，支持滚动（其余界面不动） */
.klpanel { position: fixed; top: 24px; right: 24px; z-index: 200; display: none;
  flex-direction: column; width: min(560px, 40vw); min-width: 300px;
  max-height: calc(100vh - 48px); background: #fff; border: 1px solid #d1d5db;
  border-radius: 12px; box-shadow: 0 12px 32px rgba(0,0,0,0.22); overflow: hidden; }
.klpanel.show { display: flex; }
.klpanel-hd { display: flex; align-items: center; gap: 10px; padding: 10px 14px;
  border-bottom: 1px solid #e5e7eb; font-size: 13px; font-weight: 600; color: #374151;
  background: #f9fafb; cursor: move; user-select: none; }
.klpanel-x { margin-left: auto; border: none; background: transparent; font-size: 18px;
  line-height: 1; color: #6b7280; cursor: pointer; padding: 2px 7px; border-radius: 6px; }
.klpanel-x:hover { background: #e5e7eb; color: #111827; }
.klpanel-bd { padding: 12px 14px; margin-bottom: 18px; overflow-y: auto;
  overscroll-behavior: contain;
  font-family: Consolas, "Courier New", monospace; font-size: 12.5px; line-height: 1.7;
  color: #111827; white-space: pre-wrap; word-break: break-all;
  min-height: 48px; flex: 1 1 auto; }
.klpanel-bd .klnote { font-family: "Segoe UI", "Microsoft YaHei", sans-serif; color: #6b7280; }
/* 右下角调节手柄：拖动调整面板长宽（拖顶部移动位置）。
   斜线方向为顺时针转 90° 后的 135deg；正文底部留白 18px 使滚动条整体位于手柄上方，
   有滚动条时其下箭头不会被手柄遮住。 */
.klpanel-rz { position: absolute; right: 2px; bottom: 2px; width: 15px; height: 15px;
  z-index: 5; cursor: nwse-resize;
  background: linear-gradient(135deg, transparent 0 58%, #cbd5e1 58% 68%,
    transparent 68% 80%, #cbd5e1 80% 90%, transparent 90%); }
/* 点左上角标题「输入统计」弹出设置面板（遮罩 + 中间卡片，Esc/×/点遮罩关闭） */
#ttl { cursor: pointer; }
.setmask { position: fixed; left: 0; top: 0; right: 0; bottom: 0; z-index: 300;
  background: rgba(17,24,39,0.28); display: none; }
.setmask.show { display: block; }
.setpanel { position: fixed; left: 50%; top: 50%; transform: translate(-50%,-50%); z-index: 301;
  display: none; width: 400px; max-width: calc(100vw - 32px); background: #fff;
  border: 1px solid #d1d5db; border-radius: 12px; box-shadow: 0 16px 40px rgba(0,0,0,0.25); }
.setpanel.show { display: block; }
.set-hd { display: flex; align-items: center; padding: 10px 14px; border-bottom: 1px solid #e5e7eb;
  font-size: 13px; font-weight: 600; color: #374151; background: #f9fafb;
  border-radius: 12px 12px 0 0; }
.set-x { margin-left: auto; border: none; background: transparent; font-size: 18px; line-height: 1;
  color: #6b7280; cursor: pointer; padding: 2px 7px; border-radius: 6px; }
.set-x:hover { background: #e5e7eb; color: #111827; }
.set-bd { padding: 10px 14px 14px; }
.set-sec { font-size: 12px; color: #9ca3af; margin: 8px 0 4px; }
.set-row { display: flex; align-items: center; gap: 10px; padding: 4px 0;
  font-size: 13px; color: #374151; }
.set-lb { flex: 0 0 104px; width: 104px; }
.set-row .chk { margin-top: 0; }
.set-num { width: 64px; height: 24px; padding: 0 4px; border: 1px solid #e5e7eb; border-radius: 5px;
  font-size: 13px; color: #111827; text-align: center; font-variant-numeric: tabular-nums; }
.set-num:disabled { background: #f3f4f6; color: #9ca3af; }
/* 频数分布直方图（在「每日明细数据」上方）：白底圆角卡片，与图表卡片同一套观感 */
.histsec { background: #fff; border: 1px solid #e5e7eb; border-radius: 12px;
  padding: 14px 16px; margin-top: 16px; }
#hsvg { display: block; width: 100%; height: auto; }
"""

CHART_JS = """
(function(){
  var tt = document.getElementById('tt');
  // ==== 设置（点左上角标题「输入统计」打开；只存内存，刷新页面回默认）====
  // 三个输入框的滚轮增量各自独立：auto=true = 自适应，否则每次滚 step 格。
  //   · 折线图组距 / 直方图组距 的自适应 = 跳到相邻的「好看档位」（1/2/5×10^k）；
  //   · 「隐藏 m 及以下」的自适应  = 原来那套「跳到离当前值最近的数据值」（见 wheelTh）。
  // yTop：点纵轴最顶上那个数字之后——'half' = 纵轴范围翻倍（该数字落到正中间，默认）；
  //                                    'step' = 它落到下面那一档（折线图 4/5 处）。
  var CFG = { bw: { auto: false, step: 10 }, hist: { auto: false, step: 10 },
              thr: { auto: true, step: 10 }, yTop: 'half' };
  var SET_CLOSE = null;
  // 统一的提示框出口（折线图数据点、直方图柱子都用它，即时显示、同一样式）
  function showRaw(html, e){
    if(!tt) return;
    tt.innerHTML = html;
    tt.style.display = 'block';
    move(e);
  }
  function show(el, e){
    var w = el.getAttribute('data-w'), k = el.getAttribute('data-k');
    var wd = el.getAttribute('data-wd');            // 时间后面跟星期简称（Mon/Tue…）
    var extra = (w === '0' && k === '0') ? '<div class="tt-empty">这段时间你一个字没打</div>' : '';
    showRaw('<div class="tt-time">'+el.getAttribute('data-label')+(wd ? ' ' + wd : '')+'</div>'
      + '<div class="tt-row"><span class="tt-sw"></span>上屏字数<b>'+w+'</b></div>'
      + '<div class="tt-row"><span class="tt-sk"></span>按键次数<b>'+k+'</b></div>'
      + extra, e);
  }
  function move(e){
    if(!tt) return;
    var x = e.clientX + 16, y = e.clientY + 16;
    var r = tt.getBoundingClientRect();
    if (x + r.width > window.innerWidth - 8) x = e.clientX - r.width - 16;
    if (y + r.height > window.innerHeight - 8) y = e.clientY - r.height - 16;
    tt.style.left = x + 'px';
    tt.style.top = y + 'px';
  }
  function hide(){ if(tt) tt.style.display = 'none'; }
  function isHit(t){ return t && t.getAttribute && t.getAttribute('class') === 'hit'; }

  // ==== 按键明细（keylog）：单击数据点显示该点按过的键、双击打开当天 txt 副本 ====
  // 数据由本机小服务 keylog_helper.py（127.0.0.1）提供：查看每日统计.bat 会自动后台启动它。
  var KL_BASE = 'http://127.0.0.1:47321';
  var KL_HINT = '按键明细服务未运行：请用 查看每日统计.bat 打开图表后重试';
  var ttPinned = false;
  function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
  // 跨源调用（file:// 页面）：优先 fetch，被拦时退回 JSONP，都带超时
  function klGet(path, cb){
    var done = false, t = null;
    function finish(v){ if (done) return; done = true; if (t) clearTimeout(t); cb(v); }
    function jsonp(){
      var name = '__kl_cb_' + Math.floor(Math.random() * 1e9);
      window[name] = function(v){ finish(v); };
      var tag = document.createElement('script');
      tag.src = KL_BASE + path + (path.indexOf('?') >= 0 ? '&' : '?') + 'cb=' + name;
      tag.onerror = function(){ finish(null); };
      document.body.appendChild(tag);
      t = setTimeout(function(){ finish(null); }, 2200);
    }
    if (window.fetch){
      t = setTimeout(function(){ if (!done){ t = null; jsonp(); } }, 1200);
      try {
        fetch(KL_BASE + path).then(function(r){ return r.json(); })
          .then(function(j){ finish(j); })
          .catch(function(){ if (!done){ if (t) clearTimeout(t); jsonp(); } });
      } catch (err){ if (t) clearTimeout(t); jsonp(); }
    } else {
      jsonp();
    }
  }
  // 数据点 -> 按键明细定位：分钟点=一天+分钟区间（data-kd/km1/km2）；天点=起止日期（data-kd1/kd2）
  function klRange(el){
    var a = el.getAttribute('data-km1');
    if (a !== null && a !== undefined) {
      return { min: true, d1: el.getAttribute('data-kd'), d2: el.getAttribute('data-kd'),
               m1: a, m2: el.getAttribute('data-km2') };
    }
    var b = el.getAttribute('data-kd1');
    if (b !== null && b !== undefined) {
      return { min: false, d1: b, d2: el.getAttribute('data-kd2'), m1: 0, m2: 1439 };
    }
    return null;
  }
  function klQuery(r){ return '?d1=' + r.d1 + '&d2=' + r.d2 + '&m1=' + r.m1 + '&m2=' + r.m2; }
  // 按键明细面板：单击数据点后在页面右侧的宽大面板里显示（可滚动，不挡数据点）
  var klPanel = document.getElementById('klPanel');
  var klBody = document.getElementById('klPanelBody');
  var klTitle = document.getElementById('klPanelTitle');
  function klOpen(){ if (klPanel) klPanel.className = 'klpanel show'; }
  function klClose(){ if (klPanel) klPanel.className = 'klpanel'; }
  function klSet(title, note, text){
    if (klTitle) klTitle.textContent = title || '按键明细';
    if (!klBody) return;
    klBody.innerHTML = '';
    if (note){ var nd = document.createElement('div'); nd.className = 'klnote'; nd.innerHTML = note; klBody.appendChild(nd); }
    if (text){ klBody.appendChild(document.createTextNode(text)); }
    klBody.scrollTop = 0;
    klOpen();
  }
  var klX = document.getElementById('klPanelClose');
  if (klX) klX.addEventListener('click', klClose);
  // ==== 按键明细面板可调：拖动顶部（标题栏）移动位置，拖动右下角手柄调整长宽 ====
  (function(){
    if (!klPanel) return;
    var hd = document.getElementById('klPanelHd');
    var rz = document.getElementById('klPanelRz');
    var drag = null;
    function start(e, mode){
      var p = e.touches && e.touches[0] ? e.touches[0] : e;
      var r = klPanel.getBoundingClientRect();
      drag = { mode: mode, x: p.clientX, y: p.clientY,
               l: r.left, t: r.top, w: r.width, h: r.height };
      // 从 right 定位改为 left/top 定位，之后一律用 left/top 移动
      klPanel.style.left = r.left + 'px';
      klPanel.style.top = r.top + 'px';
      klPanel.style.right = 'auto';
      if (e.preventDefault) e.preventDefault();
    }
    function onMove(e){
      if (!drag) return;
      var p = e.touches && e.touches[0] ? e.touches[0] : e;
      if (drag.mode === 'move'){
        var l = drag.l + (p.clientX - drag.x), t = drag.t + (p.clientY - drag.y);
        var vw = window.innerWidth || 0, vh = window.innerHeight || 0;
        // 不许拖出屏幕：始终留一块可抓住的边
        if (vw) l = Math.min(Math.max(l, 80 - drag.w), vw - 80);
        if (vh) t = Math.min(Math.max(t, 0), vh - 40);
        klPanel.style.left = l + 'px';
        klPanel.style.top = t + 'px';
      } else {
        var w = Math.max(300, drag.w + (p.clientX - drag.x));
        var h = Math.max(150, drag.h + (p.clientY - drag.y));
        klPanel.style.maxHeight = 'none';          // 手动调高不受屏高默认上限约束
        klPanel.style.width = w + 'px';
        klPanel.style.height = h + 'px';
      }
    }
    function onUp(){ drag = null; }
    if (hd) hd.addEventListener('mousedown', function(e){
      if (e.target && e.target.id === 'klPanelClose') return;   // ×按钮不触发移动
      start(e, 'move');
    });
    if (hd) hd.addEventListener('touchstart', function(e){ start(e, 'move'); }, { passive: false });
    if (rz) rz.addEventListener('mousedown', function(e){ start(e, 'size'); });
    if (rz) rz.addEventListener('touchstart', function(e){ start(e, 'size'); }, { passive: false });
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    document.addEventListener('touchmove', onMove, { passive: false });
    document.addEventListener('touchend', onUp);
  })();
  // 单击：把该分钟/该组距内按过的所有按键显示在右侧面板里（原样提取 txt 对应行）
  function klShowKeys(el, e){
    if (!tt) return;
    var r = klRange(el);
    if (!r) return;                      // 两种聚合都有定位信息：分钟点=日期+分钟区间，天点=起止日期
    ttPinned = true;
    show(el, e);
    var t = el.getAttribute('data-label');
    klSet(t, '<i>加载中…</i>', '');
    klGet('/keys' + klQuery(r), function(j){
      if (!j || !j.ok){ klSet(t, '<i>' + esc(KL_HINT) + '</i>', ''); return; }
      if (!j.total){ klSet(t, '<i>该时段无按键记录</i>', ''); return; }
      var out = [];
      for (var i = 0; i < j.days.length; i++){
        if (j.days.length > 1) out.push('【' + j.days[i].day + '】');
        out.push(j.days[i].text);
      }
      klSet(t, '', out.join('\\n'));
    });
  }
  // 双击：复制当天 txt、删掉对应行之前的所有内容、清掉旧副本、系统默认程序打开新副本
  // （新副本第一行就是对应行 = 自动跳到那一行）
  function klOpenCopy(el, e){
    var r = klRange(el);
    if (!r) return;
    klGet('/open' + klQuery(r), function(j){
      if (j && j.ok) return;             // 副本已被默认程序打开，这就是结果
      klSet(el.getAttribute('data-label'), '<i>'
        + esc(j && j.reason === 'no_keys' ? '该时段无按键记录，未创建副本' : KL_HINT) + '</i>', '');
    });
  }

  document.addEventListener('mouseover', function(e){
    if (ttPinned) return;
    if (isHit(e.target)) show(e.target, e);
    else if (isHBar(e.target)) showHist(e.target, e);
  });
  document.addEventListener('mousemove', function(e){ if(tt && !ttPinned && tt.style.display === 'block') move(e); });
  document.addEventListener('mouseout', function(e){
    if (!ttPinned && (isHit(e.target) || isHBar(e.target))) hide();
  });
  document.addEventListener('click', function(e){
    var a = e.target;
    if (a && a.getAttribute && String(a.getAttribute('class') || '').indexOf('ytc') >= 0
      && isYLabel(a)){ yTickClick(a); return; }
    if (a && a.getAttribute && String(a.getAttribute('class') || '').indexOf('hyt') >= 0){ yTickClick(a); return; }
    if (isHit(e.target)){ klShowKeys(e.target, e); return; }
    if (isHBar(e.target)){ histShow(e.target); ttPinned = false; hide(); return; }
    if (a && a.getAttribute && a.getAttribute('class') === 'pk'){ peakGo(a); return; }
    ttPinned = false; hide();
  });
  // ==== 纵轴最大值可改：点刻度数字，那个数字就成为该轴的纵轴最大值 ====
  // 规则：点第 f 档（该数字 = 当前最大值 × f）-> 最大值改成这个数字（图表纵向拉长，超出绘图区的部分裁掉）；
  //       点的已经是最顶上那个数字（f=1）-> 纵轴范围翻倍（最大值 ×2），那个数字就落到正中间（原来高度的一半），
  //       图表纵向缩小到原来的一半；
  //       字、键两条轴各自独立；0 那一档不响应。
  function isYLabel(el){
    return el.getAttribute('data-mode') !== null && el.getAttribute('data-mode') !== undefined;
  }
  function yTickClick(el){
    var f = parseFloat(el.getAttribute('data-f'));
    if (!(f > 0)) return;
    var hax = el.getAttribute('data-haxis');
    if (hax){
      var curH = (hax === 'w') ? HCUR.w : HCUR.k;
      // 直方图每半只有 2 档（1/2 与 1），「减半」和「下移一格」在这里结果一样：范围翻倍
    var nvH = Math.round(f >= 1 ? curH * 2 : curH * f);
      if (!(nvH > 0)) return;
      if (hax === 'w') HMAX.w = nvH; else HMAX.k = nvH;
      renderHist();
      return;
    }
    var mode = el.getAttribute('data-mode');
    var axis = el.getAttribute('data-axis');
    var cur = YCUR[mode];
    if (!cur || !YMAX[mode]) return;
    var curMax = (axis === 'k') ? cur.k : cur.w;
    // 顶格数字落到哪一档：减半 = 0.5（范围翻倍）；下移一格 = 4/5 处（范围 ×1.25）
    var nf = (CFG.yTop === 'step') ? 0.8 : 0.5;
    var nv = Math.round(f >= 1 ? curMax / nf : curMax * f);
    if (!(nv > 0)) return;
    YMAX[mode][axis] = nv;                 // 0 以外的值 = 手动最大值（自动算法不再介入）
    renderChart(mode, LASTBW[mode] || 1);  // 先按新最大值整套重画（终点状态）
    animY(mode, axis, curMax, nv);         // 再从旧比例丝滑过渡到新比例
  }
  // 纵向缩放动画：把「字」或「键」那一组几何图形以横轴（绘图区底边）为基准做 scaleY，
  // 从「旧最大值的观感」过渡到「新最大值的观感」——重画后的图形就是终点，故终点缩放为 1。
  function animY(mode, axis, oldMax, newMax){
    if (!window.requestAnimationFrame) return;          // 不支持则直接显示终点状态（无动画）
    if (!(oldMax > 0) || !(newMax > 0) || oldMax === newMax) return;
    var g = document.getElementById('g' + (axis === 'k' ? 'k' : 'w') + '-' + mode);
    if (!g || !g.setAttribute) return;
    var B = CHART_H - CHART_MB;                          // 绘图区底边（缩放基准线）
    var k0 = newMax / oldMax;                            // 起始缩放：新图 × k0 = 旧观感
    var t0 = null;
    function tf(sc){
      return 'translate(0,' + B + ') scale(1,' + sc.toFixed(4) + ') translate(0,' + (-B) + ')';
    }
    g.setAttribute('transform', tf(k0));
    function frame(ts){
      if (t0 === null) t0 = ts;
      var p = Math.min(1, (ts - t0) / 300), e = 1 - Math.pow(1 - p, 3);   // easeOutCubic
      g.setAttribute('transform', tf(k0 + (1 - k0) * e));
      if (p < 1) window.requestAnimationFrame(frame);
      else g.setAttribute('transform', '');
    }
    window.requestAnimationFrame(frame);
  }
  // 峰值链接：把对应标签页的横向滚动定位到该点（居中显示）
  function peakGo(a){
    var sc = document.getElementById(a.getAttribute('data-sc'));
    if (!sc) return;
    var x = parseFloat(a.getAttribute('data-x')) || 0;
    sc.scrollLeft = Math.max(0, x - sc.clientWidth / 2);
    if (a.getAttribute('data-sc') === 'minScroll') updateDateFix();
  }
  document.addEventListener('dblclick', function(e){ if (isHit(e.target)) klOpenCopy(e.target, e); });
  document.addEventListener('keydown', function(e){
    var k = e.key !== undefined ? e.key : e.keyCode;
    if (k === 'Escape' || k === 27){ ttPinned = false; hide(); klClose(); if (SET_CLOSE) SET_CLOSE(); }
  });

  function pad(n){ return (n < 10 ? '0' : '') + n; }
  function fmtN(n){ return Number(n).toLocaleString(); }
  function fmt1(x){ return Number(x).toLocaleString(undefined, {maximumFractionDigits: 1}); }
  function chkOn(id){ var c = document.getElementById(id); return !!(c && c.checked); }
  // 「隐藏T及以下的[上屏字数/按键次数]」输入框的当前值：整数、最小 -1（-1=不隐藏，0=隐藏0值）
  function thOf(id){
    var el = document.getElementById(id);
    var v = el ? parseInt(el.value, 10) : 0;
    if (isNaN(v)) v = 0;
    return Math.max(-1, v);
  }
  // 尾部指标按钮：点击在「上屏字数 / 按键次数」间切换（data-metric: words/keys），
  // 隐藏阈值与滚轮步长都按所选指标的数值计算
  function metricOf(btnId){
    var b = document.getElementById(btnId);
    return (b && b.getAttribute('data-metric') === 'keys') ? 2 : 1;
  }
  // 「隐藏 m 及以下的 …」的 m 按指标分别记录（每个面板一份）：切到另一个指标再切回来，
  // 数值原样恢复（例：上屏字数填 666 -> 切到按键次数显示它自己的 0 -> 切回上屏字数又是 666）。
  var THV = { dagg: { words: 0, keys: 0 }, min: { words: 0, keys: 0 } };
  function bindMetric(btnId, mode, inpId, hintId, renderFn){
    var b = document.getElementById(btnId);
    if (!b) return;
    b.addEventListener('click', function(){
      var cur = (b.getAttribute('data-metric') === 'keys') ? 'keys' : 'words';
      var next = (cur === 'keys') ? 'words' : 'keys';
      THV[mode][cur] = thOf(inpId);              // 记住当前指标下的 m
      b.setAttribute('data-metric', next);
      b.textContent = (next === 'keys') ? '按键次数' : '上屏字数';
      var inp = document.getElementById(inpId);
      if (inp) inp.value = '' + THV[mode][next];  // 换回该指标自己的 m
      var hint = document.getElementById(hintId);
      if (hint) hint.textContent = '';
      renderFn();
    });
  }
  // 「隐藏 m 及以下」输入框的滚轮自适应算法（原来那套，保留不动）：
  // 步长 = 「当前最小显示值 m」与「所有数值中离它最近的数值」的差 + 1，正好跨过一个数据值，
  // 滚一次至少隐藏/显示一组数据。src=当前组距下未过滤的桶 [时间, 字, 键]；midx：1=上屏字数、2=按键次数。
  // （设置里把这个框改成「固定增量」时不用它，见 bindThWheel。）
  function wheelTh(src, midx, th, up){
    var vals = [], i;
    for (i = 0; i < src.length; i++) vals.push(src[i][midx]);
    vals.sort(function(a, b){ return a - b; });
    if (!vals.length) return up ? th + 1 : th - 1;
    var j = 0;
    while (j < vals.length && vals[j] <= th) j++;       // j 起为显示值，之前为隐藏值
    var m = (j < vals.length) ? vals[j] : null, h = (j > 0) ? vals[j - 1] : null;
    if (m === null) return up ? th + 1 : h - 1;         // 全隐藏：只能向下显示最大一组
    var k = j;
    while (k < vals.length && vals[k] === m) k++;
    var gap = Math.min((h === null) ? Infinity : m - h, (k < vals.length) ? vals[k] - m : Infinity);
    if (!isFinite(gap)) gap = 0;
    if (up) return Math.max(th + gap + 1, m);           // 兜底：至少隐藏最小显示值那组
    return Math.min(th - gap - 1, (h === null) ? th - 1 : h - 1);   // 至少显示最大隐藏值那组
  }
  // 平均值：按「当前显示的数据」计算（含显示中的 0 值点；被阈值隐藏的点不参与）
  function avgShown(pts, idx){
    if (!pts.length) return 0;
    var s = 0;
    for (var ai = 0; ai < pts.length; ai++){ s += pts[ai][idx]; }
    return s / pts.length;
  }
  function niceMax(v){ v = +v; if (v <= 0) return 10;
    var e = Math.floor(Math.log(v) / Math.LN10); var base = Math.pow(10, e);
    var m = [1,2,5,10];
    for (var i = 0; i < m.length; i++){ if (v <= m[i] * base) return m[i] * base; }
    return 10 * base;
  }
  function keyDate(s){ return new Date(+s.substr(0,4), (+s.substr(4,2)) - 1, +s.substr(6,2), +s.substr(8,2), +s.substr(10,2)); }
  // ---- 横轴标签：时刻标在刻度行，日期统一标在每天 0:00 数据点的正下方 ----
  function fLabel(d){ return pad(d.getHours()) + ':' + pad(d.getMinutes()); }
  function fDate(d){ return d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate()); }
  function fTip(d){ return fDate(d) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()); }
  // ---- 按天聚合：横轴标每点起始日期（MM-DD），悬停显示该点覆盖的日期范围 ----
  function fLabelD(d){ return pad(d.getMonth()+1) + '-' + pad(d.getDate()); }
  function fTipD(d, bw){
    if (bw <= 1) return fDate(d);
    var e = new Date(d.getFullYear(), d.getMonth(), d.getDate() + (bw - 1));
    return fDate(d) + ' ~ ' + fDate(e) + '（' + bw + ' 天）';
  }
  function fYMD(d){ return '' + d.getFullYear() + pad(d.getMonth()+1) + pad(d.getDate()); }

  // ---- 日期 → 星期（0=周日 … 6=周六，周日为每星期的第一天）----
  // 映射表由 Python 生成：生成器用标准库 calendar（万年历）算出数据首尾之间每一天的星期，
  // 内嵌成 window.WEEKDAY={"20260926":6,…}（key=YYYYMMDD）。表里查不到时（理论上不会发生）
  // 退回浏览器本地日期计算，结果与 calendar 一致。
  var WDMAP = window.WEEKDAY || {};
  var WD_FILL = [                       // 周日→周六：金 银 红 紫 蓝 绿 黑，半透明底色（不遮折线）
    'rgba(255,255,0,0.10)',    // 0 周日 Sun   金色  #FFD700
    'rgba(192,192,192,0)',  // 1 周一 Moon  银色  #C0C0C0（纯白在浅底上看不见，用银灰）
    'rgba(255,0,0,0.10)',    // 2 周二 Mars  红色  #BC2731
    'rgba(138,43,226,0.10)',    // 3 周三 Mercury 紫色 #800080
    'rgba(30,144,225,0.10)',   // 4 周四 Jupiter 蓝色 #4169E1
    'rgba(46,204,113,0.10)',   // 5 周五 Venus 绿色  #2ECC71
    'rgba(0,0,0,0.05)'         // 6 周六 Saturn 黑色 #000000
  ];  var WD_NAME = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];   // 与 0=周日 对齐
  function wdOf(d){
    var v = WDMAP[fYMD(d)];
    return (typeof v === 'number') ? v : d.getDay();      // 浏览器 getDay() 本身就是 0=周日
  }

  // ---- 两个标签页共用的开关：平均线、星期底色 ----
  // 勾一个两个标签页一起勾、取消一起取消：状态只存一份（OPT），页面上的两个勾选框只是它的两处显示，
  // 任何一处变化都写回 OPT 并把两处勾选框刷成一致；重绘只针对当前标签页（另一页切过去时参数已变，
  // 会被 renderChart 的签名比较自动重绘）。
  var OPT = { avg: false, wd: true };
  var OPT_IDS = { avg: ['dAvgChk', 'mAvgChk'], wd: ['dWdChk', 'mWdChk'] };
  function setOpt(key, on){
    OPT[key] = on;
    var ids = OPT_IDS[key];
    for (var i = 0; i < ids.length; i++){
      var box = document.getElementById(ids[i]);
      if (box) box.checked = on;
    }
  }
  function renderActive(){ if (chkOn('s-min')) applyBm(); else applyDagg(); }

  // 元素的内容宽度（clientWidth 含左右内边距，直接拿来当绘图宽度会把图撑出卡片外）
  function contentWidth(el){
    if (!el) return anyScrollWidth();
    var w = el.clientWidth || 0;
    var cs = (window.getComputedStyle) ? window.getComputedStyle(el) : null;
    if (cs) w -= (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0);
    return w;
  }

  // 文本宽度（canvas 度量优先，失败时按字宽估算）——用于横轴刻度防重叠
  var _mc = null;
  function textW(s){
    try {
      if (_mc === null){
        var cv = document.createElement('canvas');
        _mc = (cv && cv.getContext) ? cv.getContext('2d') : false;
      }
      if (_mc){ _mc.font = '11px "Segoe UI", "Microsoft YaHei", sans-serif'; return _mc.measureText(s).width; }
    } catch (e) { _mc = false; }
    var w = 0;
    for (var wi = 0; wi < s.length; wi++){ w += s.charCodeAt(wi) > 0x2E80 ? 11 : 6.4; }
    return w;
  }
  // 标注步长：取 >= sMin 且（尽量）每天同一时刻重复的步长；找不到就用 sMin。
  // sMin 由「标签宽度 + 间隙 <= 步长 * 点距」算出，因此任何组距下标签都绝不重叠。
  function pickStride(sMin, bm){
    if (sMin <= 1) return 1;
    var perDay = Math.ceil(1440 / bm);
    if (sMin >= perDay) return perDay;
    for (var s = sMin; s < perDay; s++){
      if (1440 % (s * bm) === 0) return s;
    }
    return sMin;
  }

  // 初始显示位置 = 最右侧（最近的数据）：所有可横向滚动的图表容器滚到最右
  function scrollChartsRight(){
    var scs = document.querySelectorAll('.scroll');
    for (var si = 0; si < scs.length; si++){
      scs[si].scrollLeft = scs[si].scrollWidth;
    }
  }

  // ---- 分组：按「本地自然日」对齐，保证任何组距下每天 0:00 都恰好有一个数据点 ----
  var DAYMS = 86400000;
  function dayNumber(d){ return Math.floor(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / DAYMS); }
  function dayStartMs(dn){ var u = new Date(dn * DAYMS); return new Date(u.getUTCFullYear(), u.getUTCMonth(), u.getUTCDate()).getTime(); }

  // 按分钟聚合滚动/重绘后的日期固定标注：左侧纵轴下方显示当前视口最左数据的日期；
  // 若该日期的 0:00 标注已出现在视口里则隐藏（由 0:00 正下方的日期接管）。
  var MIN_N = 0, MIN_DX = 0, MIN_X0 = 78, MIN_PWD = 0, MIN_PTS = null, MIN_BIDX = null;
  // ==== 性能：重复渲染短路 + 隐藏面板宽度兜底 ====
  // 记住每个模块上次渲染的参数签名（组距/勾选框/容器宽度/数据量），参数没变直接跳过重绘，
  // 切换标签、重复勾选等操作瞬时完成。
  var LASTSIG = { min: null, dagg: null };
  // 各模块当前组距下「未过滤」的桶（[时间, 字, 键]），供滚轮按数值跨度跳变取该指标全部数值
  var THPTS = { min: null, dagg: null };
  // 隐藏面板里的 svg 量不到宽度时，用可见滚动容器的宽度兜底（两个面板布局宽度一致），
  // 这样后台预先渲染好的图与切过去看到的完全相同，不需要二次重绘。
  function anyScrollWidth(){
    var scs = document.querySelectorAll('.scroll'), w = 0;
    for (var si = 0; si < scs.length; si++){ if (scs[si].clientWidth > w) w = scs[si].clientWidth; }
    return w;
  }
  function minX(j){ return MIN_X0 + (MIN_N <= 1 ? MIN_PWD * 0.5 : MIN_DX * j); }
  function updateDateFix(){
    var box = document.getElementById('dateFix');
    if (!box) return;
    var sc = document.getElementById('minScroll');
    if (!sc || !MIN_PTS || !MIN_PTS.length){ box.style.display = 'none'; return; }
    var sl = sc.scrollLeft, cw = sc.clientWidth;
    var j = Math.ceil((sl - MIN_X0) / (MIN_DX || 1));
    if (j < 0) j = 0;
    if (j > MIN_PTS.length - 1) j = MIN_PTS.length - 1;
    var d = MIN_PTS[j][0];
    var ds = fDate(d);
    var bi = MIN_BIDX ? MIN_BIDX[ds] : undefined;
    if (bi !== undefined){
      var cx = minX(bi) - sl;
      if (cx >= 46 && cx <= cw - 30){ box.style.display = 'none'; return; }
    }
    box.textContent = ds;
    box.style.display = 'block';
  }

  // ==== 通用绘图引擎：「按天聚合」「按分钟聚合」共用同一段代码 ====
  // mode='min'  每 bw 分钟一个点（1–1440，按本地自然日对齐）
  // mode='dagg' 每 bw 天一个点（1–365，按自然日序号整除对齐，数据不随日期漂移）
  // 分组、隐藏阈值、平均线、固定纵轴、横轴防重叠、悬停区全部共享，两个模块不再各写一份。
  // 纵轴最大值：默认 0 = 自动（原来的 niceMax 自适应算法）；点纵轴刻度数字后变成手动值
  // （字、键各自独立）。数据口径（组距/阈值/指标）一变就作废、回到自动。
  var YMAX = { min: { w: 0, k: 0 }, dagg: { w: 0, k: 0 } };
  var YCUR = { min: null, dagg: null };     // 当前实际使用的 {w,k}（点刻度时要用）
  var YKEY = { min: '', dagg: '' };         // 数据口径签名
  var LASTBW = { min: 1, dagg: 1 };         // 当前组距（点刻度后重绘要用）
  var CHART_H = 430, CHART_MT = 58, CHART_MB = 64;

  function renderChart(mode, bw){
    var isMin = (mode === 'min');
    var svg = document.getElementById(isMin ? 'minsvg' : 'dagsvg');
    if (!svg) return;
    var raw = window.MIN_RAW || [];
    // 「隐藏T及以下的[上屏字数/按键次数]」输入框（两模块都有）：不绘制「所选指标 <= T」的点，
    // 只把其余数据按时间顺序绘制出来；T=-1 时不隐藏任何点，T=0 即原来的「隐藏0值」，
    // T>0 时图表只显示所选指标高于 T 的数据。横轴刻度/日期标注/平均值随之只按剩余的点计算。
    var th = thOf(isMin ? 'minThresh' : 'dThresh');
    var midx = metricOf(isMin ? 'minThMetric' : 'dThMetric');
    var dz = (th > -1);
    var ym = YMAX[mode];
    var kSig = bw + '|' + th + '|' + midx;
    if (YKEY[mode] !== kSig){ YKEY[mode] = kSig; ym.w = 0; ym.k = 0; }
    // 性能短路：参数与上次完全相同的重复渲染直接跳过（切标签/重复勾选时瞬时完成）
    var cw0 = (svg.parentNode && svg.parentNode.clientWidth) ? svg.parentNode.clientWidth : anyScrollWidth();
    var sig = bw + '|' + th + '|' + midx + '|' + ym.w + '|' + ym.k + '|' + (OPT.avg ? 1 : 0) + '|' + (OPT.wd ? 1 : 0)
      + '|' + cw0 + '|' + raw.length;
    if (LASTSIG[mode] === sig && svg.firstChild){
      scrollChartsRight();
      if (isMin) updateDateFix();
      return;
    }
    var pts = [], i, b, v;
    if (raw.length){
      var acc = {}, minB = Infinity, maxB = -Infinity;
      if (isMin){
        var bms = bw * 60000, perDay = Math.ceil(1440 / bw);   // 每天的组数（每天最后一组可能不足 bw 分钟）
        for (i = 0; i < raw.length; i++){
          var d0 = keyDate(raw[i][0]);
          var dn = dayNumber(d0);
          var slot = Math.floor((d0.getTime() - dayStartMs(dn)) / bms);
          if (slot > perDay - 1) slot = perDay - 1;
          b = dn * perDay + slot;
          if (!acc[b]) acc[b] = [0, 0];
          acc[b][0] += raw[i][1]; acc[b][1] += raw[i][2];
          if (b < minB) minB = b;
          if (b > maxB) maxB = b;
        }
        for (b = minB; b <= maxB; b++){
          v = acc[b] || [0, 0];
          var dn2 = Math.floor(b / perDay), slot2 = b - dn2 * perDay;
          pts.push([new Date(dayStartMs(dn2) + slot2 * bms), v[0], v[1]]);
        }
      } else {
        for (i = 0; i < raw.length; i++){
          b = Math.floor(dayNumber(keyDate(raw[i][0])) / bw);
          if (!acc[b]) acc[b] = [0, 0];
          acc[b][0] += raw[i][1]; acc[b][1] += raw[i][2];
          if (b < minB) minB = b;
          if (b > maxB) maxB = b;
        }
        for (b = minB; b <= maxB; b++){
          v = acc[b] || [0, 0];
          pts.push([new Date(dayStartMs(b * bw)), v[0], v[1]]);
        }
      }
      THPTS[mode] = pts.slice();   // 未过滤的全部桶，供滚轮按数值跨度跳变取该指标全部数值
      if (dz){
        // 隐藏「所选指标 <= 阈值」的点（th=0 即原来的隐藏0值；th=-1 不隐藏，见上）
        var fz = [];
        for (i = 0; i < pts.length; i++){
          if (pts[i][midx] > th) fz.push(pts[i]);
        }
        pts = fz;
      }
    }
    var lbl = document.getElementById(isMin ? 'minDensityLabel' : 'dDensityLabel');
    if (!pts.length){
      svg.innerHTML = '';
      if (lbl) lbl.textContent = '';
      if (isMin){ MIN_PTS = null; updateDateFix(); }
      return;
    }
    var n = pts.length;
    var SP = 9, H = CHART_H, ml = 78, mr = 78, mt = CHART_MT, mb = CHART_MB;
    // 宽度至少填满滚动容器可见区，保证左右固定纵轴贴着图表两侧
    var cw = (svg.parentNode && svg.parentNode.clientWidth) ? svg.parentNode.clientWidth : anyScrollWidth();
    var W = Math.max(n * SP + ml + mr, cw, 360);
    var pw = W - ml - mr, ph = H - mt - mb;
    var mw = 0, mk = 0, iw = 0, ik = 0;
    // 最高值取「离现在最近且最高」：数值并列时后面的点（更新的日期/时刻）覆盖前面的（用 >=）
    for (i = 0; i < n; i++){
      if (pts[i][1] >= mw){ mw = pts[i][1]; iw = i; }
      if (pts[i][2] >= mk){ mk = pts[i][2]; ik = i; }
    }
    // 纵轴最大值：手动值优先（点刻度设的），否则沿用原来的自动算法
    var wmax = ym.w > 0 ? ym.w : niceMax(mw), kmax = ym.k > 0 ? ym.k : niceMax(mk);
    function X(j){ return ml + (n <= 1 ? pw * 0.5 : pw * j / (n - 1)); }
    function Y(v, vm){ return mt + ph * (1 - v / vm); }
    // 平均值（两模块共用）：按「当前显示的数据」计算——字、键各自对显示中的全部点求平均
    // （含显示中的 0 值点，被阈值隐藏的点不参与；无显示点返回 0）
    var showAvg = OPT.avg;
    var wav = avgShown(pts, 1), kav = avgShown(pts, 2);
    var ywa = wav > 0 ? Y(wav, wmax) : 0, yka = kav > 0 ? Y(kav, kmax) : 0;
    var s = [];
    var yl = [], yr = [];
    var dxp = (n > 1) ? pw / (n - 1) : pw;
    // 「星期底色」勾选后：把每个数据点覆盖的那一天（按分钟聚合=自然日、按天聚合=该桶起始日）
    // 的背景染成该星期对应的半透明颜色。画在网格线与折线之下，不遮挡数据。
    if (OPT.wd){
      var half = dxp / 2, bi = 0;
      while (bi < n){
        var wdv = wdOf(pts[bi][0]), bj = bi;
        if (isMin){
          var dkey = fDate(pts[bi][0]);
          while (bj + 1 < n && fDate(pts[bj + 1][0]) === dkey) bj++;
        }
        var bx1 = Math.max(ml, X(bi) - half), bx2 = Math.min(ml + pw, X(bj) + half);
        if (bx2 > bx1){
          s.push('<rect x="' + bx1.toFixed(1) + '" y="' + mt + '" width="' + (bx2 - bx1).toFixed(1)
            + '" height="' + ph + '" fill="' + WD_FILL[wdv] + '"/>');
        }
        bi = bj + 1;
      }
    }
    for (var gi = 0; gi <= 5; gi++){
      var fr = gi / 5, y = mt + ph * (1 - fr);
      s.push('<line x1="'+ml+'" y1="'+y.toFixed(1)+'" x2="'+(ml+pw)+'" y2="'+y.toFixed(1)+'" stroke="#e5e7eb" stroke-width="1"/>');
      // 刻度数字带 data-f（当前是最大值的几分之几）：点一下就把它设为该轴的纵轴最大值
      yl.push('<span class="yt yt-l ytc" data-mode="'+mode+'" data-axis="w" data-f="'+(gi/5)+'" style="top:'+(y+1).toFixed(1)+'px">'+fmtN(Math.round(wmax*fr))+'</span>');
      yr.push('<span class="yt yt-r ytc" data-mode="'+mode+'" data-axis="k" data-f="'+(gi/5)+'" style="top:'+(y+1).toFixed(1)+'px">'+fmtN(Math.round(kmax*fr))+'</span>');
    }
    // 平均值标注：不在线上写「字数/键数」，只把数值放到对应侧坐标轴区域的对应高度（与平均线齐平）
    if (showAvg && wav > 0) yl.push('<span class="yt yt-l avgv" style="top:'+(ywa+1).toFixed(1)+'px">'+fmt1(wav)+'</span>');
    if (showAvg && kav > 0) yr.push('<span class="yt yt-r avgv" style="top:'+(yka+1).toFixed(1)+'px">'+fmt1(kav)+'</span>');
    yl.push('<span class="yt yt-l yt-title" style="top:'+(mt-11)+'px">字</span>');
    yr.push('<span class="yt yt-r yt-title" style="top:'+(mt-11)+'px">键</span>');
    // 纵轴刻度固定显示在滚动区左右两侧，不随图表横向滚动
    var boxL = document.getElementById(isMin ? 'yaxL' : 'yaxL2'), boxR = document.getElementById(isMin ? 'yaxR' : 'yaxR2');
    if (boxL) boxL.innerHTML = yl.join('');
    if (boxR) boxR.innerHTML = yr.join('');
    s.push('<line x1="'+ml+'" y1="'+(mt+ph)+'" x2="'+(ml+pw)+'" y2="'+(mt+ph)+'" stroke="#9ca3af" stroke-width="1.2"/>');
    // 日分隔线 + 日期标注（仅按分钟聚合）：日期画在每天 0:00 数据点的正下方（= 此点以右当天数据的日期）
    // 防重叠：组距很大时（如 1440 分钟=每天一个点）每个点都是 0:00，按点距根本放不下日期。
    // 因此日期文字按「相邻两个标注的文字边界之间至少留 8px」逐个放行——放不下就跳过不标，
    // 隔够距离才标一次（日分隔线始终保留，所以仍然看得出每天的分界）。
    var bidx = {}, lastDay = '', lastDateRight = -1e9;
    if (isMin){
      for (i = 0; i < n; i++){
        var dd = pts[i][0];
        var ds3 = fDate(dd);
        // 正常：日期标在每天 0:00 的点正下方；设了隐藏阈值后 0:00 的点可能被隐藏，
        // 改为标在每天第一个剩下的数据点正下方（横轴标注随隐藏后的数据自动跟随）
        var mark = dz ? (ds3 !== lastDay) : (dd.getHours() === 0 && dd.getMinutes() === 0);
        lastDay = ds3;
        if (mark){
          var x3 = X(i), lw = textW(ds3);
          s.push('<line x1="'+x3.toFixed(1)+'" y1="'+mt+'" x2="'+x3.toFixed(1)+'" y2="'+(mt+ph)+'" stroke="#d1d5db" stroke-width="1" stroke-dasharray="3 4"/>');
          if (x3 - lw / 2 >= lastDateRight + 8){
            s.push('<text x="'+x3.toFixed(1)+'" y="'+(mt+ph+42)+'" class="xl xd" text-anchor="middle">'+ds3+'</text>');
            lastDateRight = x3 + lw / 2;
            bidx[ds3] = i;
          }
        }
      }
    }
    // 横轴刻度：步长由实际文本宽度与点距决定，任何组距都不重叠
    var labW = isMin
      ? Math.max(textW('00:00'), textW('12:34'), textW('23:59'))
      : Math.max(textW('01-02'), textW('12-31'));
    var stride = Math.max(1, Math.ceil((labW + 12) / (dxp || 1)));
    // 按分钟聚合未隐藏数据时点等间隔，尽量让时刻标注每天同一时刻重复
    if (isMin && !dz) stride = pickStride(stride, bw);
    if (stride > n) stride = n;
    for (i = 0; i < n; i += stride){
      s.push('<text x="'+X(i).toFixed(1)+'" y="'+(mt+ph+22)+'" class="xl" text-anchor="middle">'
        + (isMin ? fLabel(pts[i][0]) : fLabelD(pts[i][0])) + '</text>');
    }
    var wp = [], kp = [];
    for (i = 0; i < n; i++){ wp.push(X(i).toFixed(1) + ',' + Y(pts[i][1], wmax).toFixed(1)); kp.push(X(i).toFixed(1) + ',' + Y(pts[i][2], kmax).toFixed(1)); }
    // 字/键的几何图形分进两个 <g>：点纵轴刻度改最大值时，只对对应那一组做纵向缩放动画
    var gW = [], gK = [];
    // 平均线（勾选后显示）：字=淡蓝实线（左轴高度）、键=淡橙虚线（右轴高度）；
    // 不在线上写「字数/键数」，平均数值标在对应侧坐标轴区域的对应高度（见上方纵轴刻度区）
    if (showAvg && wav > 0){
      gW.push('<line x1="'+ml+'" y1="'+ywa.toFixed(1)+'" x2="'+(ml+pw)+'" y2="'+ywa.toFixed(1)+'" stroke="#93c5fd" stroke-width="1.5"/>');
    }
    if (showAvg && kav > 0){
      gK.push('<line x1="'+ml+'" y1="'+yka.toFixed(1)+'" x2="'+(ml+pw)+'" y2="'+yka.toFixed(1)+'" stroke="#fcd34d" stroke-width="1.5" stroke-dasharray="3 3"/>');
    }
    // 按键次数折线：实线（2026-10-24 起由虚线改为实线，与上屏字数一样用实线区分颜色）
    gK.push('<polyline points="'+kp.join(' ')+'" fill="none" stroke="__CK__" stroke-width="2" stroke-linejoin="round"/>');
    gW.push('<polyline points="'+wp.join(' ')+'" fill="none" stroke="__CW__" stroke-width="2.5" stroke-linejoin="round"/>');
    for (i = 0; i < n; i++){
      var x = X(i);
      gK.push('<circle cx="'+x.toFixed(1)+'" cy="'+Y(pts[i][2], kmax).toFixed(1)+'" r="3.2" fill="__CK__"/>');
      gW.push('<circle cx="'+x.toFixed(1)+'" cy="'+Y(pts[i][1], wmax).toFixed(1)+'" r="3.2" fill="__CW__"/>');
    }
    // 悬停命中区（透明大圆，带数据，供 JS 提示框显示）
    for (i = 0; i < n; i++){
      var x2 = X(i);
      var at = 'data-label="' + (isMin ? fTip(pts[i][0]) : fTipD(pts[i][0], bw))
        + '" data-w="' + fmtN(pts[i][1]) + '" data-k="' + fmtN(pts[i][2]) + '"'
        + ' data-wd="' + WD_NAME[wdOf(pts[i][0])] + '"';
      // 按键明细定位信息：分钟点=日期+分钟区间；天点=起止日期（供单击/双击取 keylog 用）
      if (isMin){
        var dm = pts[i][0], b1 = dm.getHours() * 60 + dm.getMinutes();
        at += ' data-kd="'+fYMD(dm)+'" data-km1="'+b1+'" data-km2="'+Math.min(1439, b1 + bw - 1)+'"';
      } else {
        var de = new Date(pts[i][0].getFullYear(), pts[i][0].getMonth(), pts[i][0].getDate() + (bw - 1));
        at += ' data-kd1="'+fYMD(pts[i][0])+'" data-kd2="'+fYMD(de)+'"';
      }
      gK.push('<circle class="hit" cx="'+x2.toFixed(1)+'" cy="'+Y(pts[i][2], kmax).toFixed(1)+'" r="14" '+at+'/>');
      gW.push('<circle class="hit" cx="'+x2.toFixed(1)+'" cy="'+Y(pts[i][1], wmax).toFixed(1)+'" r="14" '+at+'/>');
    }
    // 绘图区裁剪：手动把纵轴最大值调小后，超出的折线/点不会画到绘图区外面
    s.push('<defs><clipPath id="cpl-'+mode+'"><rect x="'+ml+'" y="'+mt+'" width="'+pw+'" height="'+ph+'"/></clipPath></defs>');
    s.push('<g clip-path="url(#cpl-'+mode+')">'
      + '<g id="gk-'+mode+'">'+gK.join('')+'</g>'
      + '<g id="gw-'+mode+'">'+gW.join('')+'</g></g>');
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    svg.setAttribute('width', W); svg.setAttribute('height', H);
    svg.style.width = W + 'px'; svg.style.height = H + 'px';
    svg.innerHTML = s.join('');
    // 峰值：最高的字/键各带一个可点链接，点击把折线图横向滚到那个数据点
    if (lbl){
      var scId = isMin ? 'minScroll' : 'dScroll';
      function pkLink(v, t, idx){
        return '<a class="pk" data-sc="' + scId + '" data-x="' + X(idx).toFixed(0) + '">'
          + fmtN(v) + t + '（' + (isMin ? fTip(pts[idx][0]) : fDate(pts[idx][0])) + '）</a>';
      }
      lbl.innerHTML = '共 ' + n + ' 点 · 最高' + pkLink(mw, '字', iw) + '，' + pkLink(mk, '键', ik);
    }
    if (isMin){
      // 供滚动时更新左下角固定日期用
      MIN_N = n; MIN_DX = dxp; MIN_X0 = ml; MIN_PWD = pw; MIN_PTS = pts; MIN_BIDX = bidx;
      updateDateFix();
    }
    // 记录本次渲染参数签名，供后续重复渲染短路
    YCUR[mode] = { w: wmax, k: kmax };
    LASTBW[mode] = bw;
    LASTSIG[mode] = sig;
    // 每次重绘（含切换组距/勾选框）后都回到最右侧
    scrollChartsRight();
  }

  // 组距输入 + 「绘图」按钮（两模块共用）：允许输入 1–maxV 的任意整数，超出范围自动收敛并提示
  function applyGroup(inpId, hintId, maxV, unit, renderFn){
    var inp = document.getElementById(inpId);
    if (!inp){ renderFn(1); return; }
    var hint = document.getElementById(hintId);
    var v = parseInt(inp.value, 10);
    var msg = '';
    if (isNaN(v)){ v = 1; msg = '请输入 1–' + maxV + ' 之间的整数，已按 1 ' + unit + '绘图'; }
    else {
      var c = Math.min(maxV, Math.max(1, v));
      if (c !== v){ msg = '输入超出 1–' + maxV + ' 范围，已按 ' + c + ' ' + unit + '绘图'; }
      v = c;
    }
    inp.value = v;
    if (hint) hint.textContent = msg;
    renderFn(v);
  }
  // ==== 频数分布直方图（页面下方，位于「每日明细数据」上方）====
  // 口径：
  //   * 数据 = 当前标签页折线图的那一批时间桶（同一组距、同一「隐藏 … 及以下的 …」阈值与指标，
  //     被阈值隐藏的桶不参与），因此两个图永远看的是同一堆数据；
  //   * 横轴 = 桶的数值（左=按上屏字数分箱、右=按按键次数分箱），纵轴 = 落在该数值区间的桶个数
  //     （频数），字、键共用同一根纵轴，零点在下方、越上越大；
  //   * 每个区间内左柱=上屏字数、右柱=按键次数；
  //   * 组距（每个区间的数值宽度）默认跟随折线图的组距，可单独修改；组数超过上限（HIST_MAXBINS=120，
  //     且不超过数据点个数）时按 1/2/5×10^k 自动放大——按天聚合的「组距=1 天」会得到上万根细到
  //     看不见的柱子，必须收敛。
  var HIST_MAXBINS = 120;
  // 当前直方图的状态：pts=当前标签页的桶、bin=组距、wc/kc=各区间频数（提示框/单击面板取数用）
  var HST = { pts: [], bin: 1, mode: 'dagg', bw: 1, wc: [], kc: [] };
  function histBinInput(){ return document.getElementById('hBin'); }
  function histMode(){ return chkOn('s-min') ? 'min' : 'dagg'; }
  // 组距默认跟随折线图：只有「当前标签页变了」或「该页的组距变了」才把组距回填成折线图的组距，
  // 勾平均线/星期底色之类的操作不会把手工改过的直方图组距冲掉。
  var HSTAT = { mode: null, bw: null };
  // 与 renderChart 相同的过滤口径：所选指标 <= 阈值的桶不参与（阈值 -1 = 不隐藏任何桶）
  function histSrc(mode){
    var src = THPTS[mode] || [];
    if (!src.length) return [];
    var isMin = (mode === 'min');
    var th = thOf(isMin ? 'minThresh' : 'dThresh');
    var midx = metricOf(isMin ? 'minThMetric' : 'dThMetric');
    if (th <= -1) return src.slice();
    var out = [];
    for (var i = 0; i < src.length; i++){ if (src[i][midx] > th) out.push(src[i]); }
    return out;
  }
  // 下一个「好看的」组距（1/2/5×10^k，>= v），用于组数过多时放大
  function niceStepUp(v){
    if (!(v > 1)) return 1;
    var e = Math.floor(Math.log(v) / Math.LN10), base = Math.pow(10, e), m = [1, 2, 5, 10];
    for (var i = 0; i < m.length; i++){ if (m[i] * base >= v - 1e-9) return m[i] * base; }
    return 10 * base;
  }
  // 纵轴最大值（直方图）：0=自动（原 niceEven 自适应）；点纵轴刻度数字后改成手动值（字、键各自独立）。
  // 数据口径（标签页/组距/阈值/指标/点数）一变就作废、回到自动。
  var HMAX = { w: 0, k: 0 };
  var HCUR = { w: 1, k: 1 };     // 当前实际使用的 {w,k}（点刻度时要用）
  var HKEY = '';                 // 数据口径签名
  var HPREV = null;              // 上次绘制的 {wt,kt}，用于纵轴缩放动画
  function renderHist(chartBw){
    var svg = document.getElementById('hsvg');
    var binEl = histBinInput();
    var mode = histMode(), pts = histSrc(mode);
    var i, vmax = 0;
    for (i = 0; i < pts.length; i++){
      if (pts[i][1] > vmax) vmax = pts[i][1];
      if (pts[i][2] > vmax) vmax = pts[i][2];
    }
    // 组距默认跟随折线图：切换标签页 / 该页组距变了才回填；回填时顺带把组数收敛到
    // 「不超过 120 组、也不超过数据点个数」的合理范围（否则按天聚合的 组距=1 天会有上万组）。
    if (chartBw !== undefined && chartBw !== null && (HSTAT.mode !== mode || HSTAT.bw !== chartBw)){
      HSTAT.mode = mode; HSTAT.bw = chartBw;
      var dflt = Math.max(1, chartBw), cap = Math.min(HIST_MAXBINS, Math.max(10, pts.length));
      while (Math.floor(vmax / dflt) + 1 > cap){ dflt = niceStepUp(dflt + 1); }
      if (binEl) binEl.value = '' + dflt;
    }
    if (!svg) return;
    if (!pts.length){ svg.innerHTML = ''; HPREV = null; return; }
    // 手工输入的组距同样收敛：只受 120 组这一条硬上限约束
    var bin = binEl ? parseInt(binEl.value, 10) : NaN;
    if (isNaN(bin) || bin < 1) bin = 1;
    var nb = Math.floor(vmax / bin) + 1;
    while (nb > HIST_MAXBINS){ bin = niceStepUp(bin + 1); nb = Math.floor(vmax / bin) + 1; }
    if (binEl && binEl.value !== '' + bin) binEl.value = '' + bin;
    var wc = [], kc = [];
    for (i = 0; i < nb; i++){ wc.push(0); kc.push(0); }
    for (i = 0; i < pts.length; i++){
      var iw = Math.floor(pts[i][1] / bin), ik = Math.floor(pts[i][2] / bin);
      if (iw > nb - 1) iw = nb - 1;
      if (ik > nb - 1) ik = nb - 1;
      wc[iw]++; kc[ik]++;
    }
    var wcMax = 0, kcMax = 0;
    for (i = 0; i < nb; i++){
      if (wc[i] > wcMax) wcMax = wc[i];
      if (kc[i] > kcMax) kcMax = kc[i];
    }
    // 供提示框/单击面板取数（数据都在页面里，不需要访问后端）
    HST.pts = pts; HST.bin = bin; HST.mode = mode; HST.bw = Math.max(1, chartBw || HSTAT.bw || 1);
    HST.wc = wc; HST.kc = kc;

    // 数据口径变了：手动纵轴最大值作废、回到自动（也不做缩放动画）
    var hTh = thOf(mode === 'min' ? 'minThresh' : 'dThresh');
    var hMi = metricOf(mode === 'min' ? 'minThMetric' : 'dThMetric');
    var hk = mode + '|' + bin + '|' + hTh + '|' + hMi + '|' + pts.length;
    if (HKEY !== hk){ HKEY = hk; HMAX.w = 0; HMAX.k = 0; HPREV = null; }

    var W = Math.max(contentWidth(svg.parentNode), 360), H = 340, ml = 56, mr = 18, mt = 26, mb = 40;
    var pw = W - ml - mr, ph = H - mt - mb, mid = mt + ph / 2, half = ph / 2;
    // 上下两半各自取整到「偶数」刻度，保证 1/2 处的刻度线也是整数
    function niceEven(v){ var m = niceMax(v); return (m % 2) ? m + 1 : m; }
    // 纵轴最大值：手动值优先，否则沿用原来的自动算法
    var wt = HMAX.w > 0 ? HMAX.w : niceEven(wcMax), kt = HMAX.k > 0 ? HMAX.k : niceEven(kcMax);
    HCUR = { w: wt, k: kt };
    var gw = pw / nb, bw = Math.max(1, Math.min(gw * 0.6, 24));

    // 按给定的上下最大值整套画一遍（两半各自按比例缩放；动画时逐帧用插值调用它）
    function paint(topW, topK){
      function YW(v){ return mid - half * (v / topW); }      // 上屏字数：横轴上方
      function YK(v){ return mid + half * (v / topK); }      // 按键次数：横轴下方
      var s = [];
      var cW = 'style="fill:__CW__"', cK = 'style="fill:__CK__"';
      // 上下两侧各画 1/2、1 两条参考线，刻度按各自量级标（蓝=字、橙=键）
      for (var j = 1; j <= 2; j++){
        var fr = j / 2, yw = YW(topW * fr), yk = YK(topK * fr);
        s.push('<line x1="'+ml+'" y1="'+yw.toFixed(1)+'" x2="'+(ml+pw)+'" y2="'+yw.toFixed(1)+'" stroke="#e5e7eb" stroke-width="1"/>');
        s.push('<text x="'+(ml - 8)+'" y="'+(yw + 4).toFixed(1)+'" class="xl hyt" text-anchor="end" data-haxis="w" data-f="'+fr+'" '+cW+'>'+fmtN(Math.round(topW * fr))+'</text>');
        s.push('<line x1="'+ml+'" y1="'+yk.toFixed(1)+'" x2="'+(ml+pw)+'" y2="'+yk.toFixed(1)+'" stroke="#e5e7eb" stroke-width="1"/>');
        s.push('<text x="'+(ml - 8)+'" y="'+(yk + 4).toFixed(1)+'" class="xl hyt" text-anchor="end" data-haxis="k" data-f="'+fr+'" '+cK+'>'+fmtN(Math.round(topK * fr))+'</text>');
      }
      // 中轴（0）：字向上、键向下
      s.push('<line x1="'+ml+'" y1="'+mid.toFixed(1)+'" x2="'+(ml+pw)+'" y2="'+mid.toFixed(1)+'" stroke="#9ca3af" stroke-width="1"/>');
      s.push('<text x="'+(ml - 8)+'" y="'+(mid + 4).toFixed(1)+'" class="xl" text-anchor="end">0</text>');
      // 柱子：每个区间同一列，上=上屏字数（向上）、下=按键次数（向下）；超出绘图区的部分裁掉
      var bars = [];
      for (var k2 = 0; k2 < nb; k2++){
        var bx = ml + k2 * gw + (gw - bw) / 2;
        if (wc[k2] > 0){
          bars.push('<rect x="'+bx.toFixed(1)+'" y="'+YW(wc[k2]).toFixed(1)+'" width="'+bw.toFixed(1)
            +'" height="'+(mid - YW(wc[k2])).toFixed(1)+'" fill="__CW__"/>');
        }
        if (kc[k2] > 0){
          bars.push('<rect x="'+bx.toFixed(1)+'" y="'+mid.toFixed(1)+'" width="'+bw.toFixed(1)
            +'" height="'+(YK(kc[k2]) - mid).toFixed(1)+'" fill="__CK__"/>');
        }
      }
      // 命中区：只有「柱子本身」那条矩形可命中（柱与柱之间的空白不弹提示框、也不响应单击）；
      // 频数为 0 的区间没有柱子，自然没有命中区。极矮的柱子给 6px 最小高度，否则点不到。
      var hitS = [];
      for (var k3 = 0; k3 < nb; k3++){
        var hx = ml + k3 * gw + (gw - bw) / 2;
        if (wc[k3] > 0){
          var wh = Math.max(6, mid - YW(wc[k3]));
          hitS.push('<rect class="hhit" x="'+hx.toFixed(1)+'" y="'+(mid - wh).toFixed(1)+'" width="'+bw.toFixed(1)
            +'" height="'+wh.toFixed(1)+'" data-b="'+k3+'" data-s="w" data-n="'+wc[k3]+'"/>');
        }
        if (kc[k3] > 0){
          var kh = Math.max(6, YK(kc[k3]) - mid);
          hitS.push('<rect class="hhit" x="'+hx.toFixed(1)+'" y="'+mid.toFixed(1)+'" width="'+bw.toFixed(1)
            +'" height="'+kh.toFixed(1)+'" data-b="'+k3+'" data-s="k" data-n="'+kc[k3]+'"/>');
        }
      }
      s.push('<defs><clipPath id="cpl-h"><rect x="'+ml+'" y="'+mt+'" width="'+pw+'" height="'+ph+'"/></clipPath></defs>');
      s.push('<g clip-path="url(#cpl-h)">'+bars.join('')+hitS.join('')+'</g>');
      // 横轴数值刻度：按文字宽度自动稀疏，绝不重叠（标在最下面一行）
      var labW = Math.max(textW(fmtN(0)), textW(fmtN((nb - 1) * bin)), textW(fmtN(nb * bin)));
      var stride = Math.max(1, Math.ceil((labW + 14) / (gw || 1)));
      for (var k4 = 0; k4 < nb; k4 += stride){
        s.push('<text x="'+(ml + k4 * gw).toFixed(1)+'" y="'+(mid + half + 18).toFixed(1)+'" class="xl" text-anchor="middle">'+fmtN(k4 * bin)+'</text>');
      }
      // 图例（与折线图同一套样式）
      s.push('<rect x="'+ml+'" y="5" width="11" height="11" fill="__CW__"/>');
      s.push('<text x="'+(ml + 16)+'" y="15" class="legend">上屏字数</text>');
      s.push('<rect x="'+(ml + 100)+'" y="5" width="11" height="11" fill="__CK__"/>');
      s.push('<text x="'+(ml + 116)+'" y="15" class="legend">按键次数</text>');
      svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
      svg.setAttribute('width', W); svg.setAttribute('height', H);
      svg.style.width = W + 'px'; svg.style.height = H + 'px';
      svg.innerHTML = s.join('');
    }

    var prev = HPREV;
    HPREV = { wt: wt, kt: kt };
    if (prev && window.requestAnimationFrame && (prev.wt !== wt || prev.kt !== kt)){
      // 点刻度改了纵轴最大值：从旧比例丝滑过渡到新比例
      var w0 = prev.wt, k0 = prev.kt, t0 = 0;
      paint(w0, k0);
      var step = function(ts){
        if (!t0) t0 = ts;
        var p = Math.min(1, (ts - t0) / 300), e = 1 - Math.pow(1 - p, 3);
        paint(w0 + (wt - w0) * e, k0 + (kt - k0) * e);
        if (p < 1) window.requestAnimationFrame(step);
        else paint(wt, kt);
      };
      window.requestAnimationFrame(step);
    } else {
      paint(wt, kt);
    }
  }

  // 直方图柱子：悬停用与折线图同一个提示框（即时显示），单击在右侧面板列出全部命中时段
  function isHBar(t){ return t && t.getAttribute && t.getAttribute('class') === 'hhit'; }
  function histBinOf(el){
    var b = parseInt(el.getAttribute('data-b'), 10) || 0;
    return { b: b, lo: b * HST.bin, hi: b * HST.bin + HST.bin - 1, k: el.getAttribute('data-s') === 'k' };
  }
  function showHist(el, e){
    if (!HST.wc.length) return;
    var r = histBinOf(el);
    showRaw('<div class="tt-time">'+fmtN(r.lo)+'–'+fmtN(r.hi)+'</div>'
      + '<div class="tt-row"><span class="tt-sw"></span>上屏字数<b>'+fmtN(HST.wc[r.b])+' 个时段</b></div>'
      + '<div class="tt-row"><span class="tt-sk"></span>按键次数<b>'+fmtN(HST.kc[r.b])+' 个时段</b></div>', e);
  }
  function histShow(el){
    if (!HST.wc.length) return;
    var r = histBinOf(el), idx = r.k ? 2 : 1, out = [];
    for (var i = 0; i < HST.pts.length; i++){
      var v = HST.pts[i][idx];
      if (v < r.lo || v > r.hi) continue;
      out.push((HST.mode === 'min' ? fTip(HST.pts[i][0]) : fTipD(HST.pts[i][0], HST.bw))
        + '   ' + fmtN(HST.pts[i][1]) + ' 字 / ' + fmtN(HST.pts[i][2]) + ' 键');
    }
    if (!out.length) return;                       // 空区间不弹面板（悬停提示已说明 0 个时段）
    klSet((r.k ? '按键次数 ' : '上屏字数 ') + fmtN(r.lo) + '–' + fmtN(r.hi)
      + '（' + out.length + ' 个时段）', '', out.join('\\n'));
  }

  function renderMin(bm){ renderChart('min', bm); renderHist(bm); }        // 按分钟聚合：默认 1 分钟
  function renderDayAgg(bw){ renderChart('dagg', bw); renderHist(bw); }    // 按天聚合：默认 1 天
  function applyBm(){ applyGroup('bmInput', 'bmHint', 1440, '分钟', renderMin); }
  function applyDagg(){ applyGroup('dInput', 'dHint', 365, '天', renderDayAgg); }

  function bindCtl(inpId, btnId, fn){
    var inp = document.getElementById(inpId);
    var btn = document.getElementById(btnId);
    if (btn) btn.addEventListener('click', fn);
    if (inp){
      inp.addEventListener('change', fn);
      inp.addEventListener('keydown', function(e){
        var k = e.key !== undefined ? e.key : e.keyCode;
        if (k === 'Enter' || k === 13){ e.preventDefault(); fn(); }
      });
    }
  }
  // 共用开关的绑定：任一勾选框变化 -> 写回 OPT + 同步另一处勾选框 + 重绘当前标签页
  function bindOpt(key){
    var ids = OPT_IDS[key];
    for (var i = 0; i < ids.length; i++){
      (function(id){
        var el = document.getElementById(id);
        if (el) el.addEventListener('change', function(){ setOpt(key, !!el.checked); renderActive(); });
      })(ids[i]);
    }
  }
  // 「隐藏T及以下的[上屏字数/按键次数]」输入框绑定（两模块同一套）：整数、最小 -1、默认 0；
  // 越界/非法输入自动收敛并提示。点上下箭头（input 事件）即时重绘，
  // 失焦/回车（change 事件）把值规整回写。
  function applyTh(inpId, hintId, renderFn, commit){
    var inp = document.getElementById(inpId);
    if (!inp){ renderFn(); return; }
    var hint = document.getElementById(hintId);
    var raw = (inp.value === undefined || inp.value === null) ? '' : String(inp.value).trim();
    var v = parseInt(raw, 10);
    var msg = '';
    if (isNaN(v)){
      if (!commit && raw === ''){ return; }    // 数字还没写完，不打断输入
      if (raw !== ''){ msg = '只能输入不小于 -1 的整数，已按 0 处理'; }
      v = 0;
    } else if (v < -1){
      v = -1; msg = '最小为 -1，已按 -1 处理';
    } else if (raw !== '' + v){
      msg = '只能输入整数，已按 ' + v + ' 处理';
    }
    if (inp.value !== '' + v){ inp.value = '' + v; }
    if (hint){ hint.textContent = msg; }
    renderFn();
  }
  function bindTh(inpId, hintId, renderFn){
    var inp = document.getElementById(inpId);
    if (!inp) return;
    inp.addEventListener('input', function(){ applyTh(inpId, hintId, renderFn, false); });
    inp.addEventListener('change', function(){ applyTh(inpId, hintId, renderFn, true); });
    inp.addEventListener('keydown', function(e){
      var k = e.key !== undefined ? e.key : e.keyCode;
      if (k === 'Enter' || k === 13){ e.preventDefault(); applyTh(inpId, hintId, renderFn, true); }
    });
  }
  // 阈值输入框的滚轮（两模块同一套）：滚一格按「设置」里的增量走——
  // 自适应 = 跳到离当前值最近的数据值（wheelTh，默认）；固定增量 = ±step。最小 -1。
  function bindThWheel(inpId, mode, btnId, renderFn){
    var inp = document.getElementById(inpId);
    if (!inp) return;
    inp.addEventListener('wheel', function(e){
      if (document.activeElement !== inp) return;   // 与原生一致：先点进输入框再滚动
      if (e.preventDefault) e.preventDefault();
      var up = ((e.deltaY || 0) < 0);
      var th = thOf(inpId);
      var v = CFG.thr.auto
        ? wheelTh(THPTS[mode] || [], metricOf(btnId), th, up)
        : th + (up ? CFG.thr.step : -CFG.thr.step);
      inp.value = '' + Math.max(-1, Math.round(v));
      renderFn();
    }, { passive: false });
  }
  // 「组距」输入框的滚轮（折线图组距 / 直方图组距共用）：自适应 = 相邻好看档位，否则 ±step；
  // 上下箭头仍是原生 ±1。跳完照常走一遍输入框的收敛与重绘（见 applyFn）。
  function niceUp(v){
    if (!(v > 0)) return 1;
    var e = Math.floor(Math.log(v) / Math.LN10), base = Math.pow(10, e), m = [1, 2, 5, 10];
    for (var i = 0; i < m.length; i++){ var c = m[i] * base; if (c > v + 1e-9) return Math.round(c); }
    return Math.round(10 * base);
  }
  function niceDown(v){
    if (!(v > 1)) return 1;
    var e = Math.floor(Math.log(v) / Math.LN10), base = Math.pow(10, e), m = [5, 2, 1];
    for (var i = 0; i < m.length; i++){ var c = m[i] * base; if (c < v - 1e-9) return Math.round(c); }
    return Math.max(1, Math.round(base / 2));
  }
  function bindGroupWheel(inpId, maxV, cfgKey, applyFn){
    var inp = document.getElementById(inpId);
    if (!inp) return;
    inp.addEventListener('wheel', function(e){
      if (document.activeElement !== inp) return;
      if (e.preventDefault) e.preventDefault();
      var up = ((e.deltaY || 0) < 0);
      var cur = parseInt(inp.value, 10);
      if (isNaN(cur) || cur < 1) cur = 1;
      var c = CFG[cfgKey];
      var v = c.auto ? (up ? niceUp(cur) : niceDown(cur)) : cur + (up ? c.step : -c.step);
      v = Math.round(v);
      if (maxV) v = Math.min(maxV, v);
      inp.value = '' + Math.max(1, v);
      applyFn();
    }, { passive: false });
  }
  // ==== 设置面板（点左上角标题「输入统计」打开；Esc / × / 点遮罩关闭）====
  // 一行 = 一个数值框 + 一个「自适应」勾选框；勾上自适应就把数值框灰掉（值仍记着）。
  function bindCfgNum(numId, autoId, key){
    var n = document.getElementById(numId);
    if (!n) return;
    var a = document.getElementById(autoId);
    function sync(){
      CFG[key].auto = !!(a && a.checked);
      n.disabled = CFG[key].auto;
      var v = parseInt(n.value, 10);
      if (!isNaN(v) && v >= 1) CFG[key].step = v;
      else n.value = '' + CFG[key].step;
    }
    if (a) a.addEventListener('change', sync);
    n.addEventListener('change', sync);
    n.addEventListener('input', function(){
      var v = parseInt(n.value, 10);
      if (!isNaN(v) && v >= 1) CFG[key].step = v;
    });
  }
  function bindSettings(){
    var box = document.getElementById('setPanel'), mask = document.getElementById('setMask');
    function openSet(){
      if (mask) mask.className = 'setmask show';
      if (box) box.className = 'setpanel show';
    }
    function closeSet(){
      if (mask) mask.className = 'setmask';
      if (box) box.className = 'setpanel';
    }
    SET_CLOSE = closeSet;
    var ttl = document.getElementById('ttl');
    if (ttl) ttl.addEventListener('click', openSet);
    var x = document.getElementById('setClose');
    if (x) x.addEventListener('click', closeSet);
    if (mask) mask.addEventListener('click', closeSet);
    bindCfgNum('cfgBw', 'cfgBwAuto', 'bw');
    bindCfgNum('cfgThr', 'cfgThrAuto', 'thr');
    bindCfgNum('cfgHist', 'cfgHistAuto', 'hist');
    var half = document.getElementById('cfgYHalf'), step = document.getElementById('cfgYStep');
    if (half) half.addEventListener('change', function(){ if (half.checked) CFG.yTop = 'half'; });
    if (step) step.addEventListener('change', function(){ if (step.checked) CFG.yTop = 'step'; });
  }
  try {
    bindCtl('bmInput', 'bmApply', applyBm);
    bindCtl('dInput', 'dApply', applyDagg);
    bindTh('minThresh', 'minThHint', applyBm); bindTh('dThresh', 'dThHint', applyDagg);
    // 平均线、星期底色：两个标签页共用一个开关；直方图「组距」输入框单独绑定
    bindOpt('avg'); bindOpt('wd');
    bindCtl('hBin', 'hApply', function(){ renderHist(); });
    bindMetric('minThMetric', 'min', 'minThresh', 'minThHint', applyBm);
    bindMetric('dThMetric', 'dagg', 'dThresh', 'dThHint', applyDagg);
    bindThWheel('minThresh', 'min', 'minThMetric', applyBm);
    bindThWheel('dThresh', 'dagg', 'dThMetric', applyDagg);
    bindGroupWheel('bmInput', 1440, 'bw', applyBm);        // 折线图组距（按分钟聚合）
    bindGroupWheel('dInput', 365, 'bw', applyDagg);        // 折线图组距（按天聚合）
    bindGroupWheel('hBin', 0, 'hist', function(){ renderHist(); });   // 直方图组距
    bindSettings();
    // 横向滚动/窗口尺寸变化时，同步更新左下角固定的日期标注
    var sc0 = document.getElementById('minScroll');
    if (sc0) sc0.addEventListener('scroll', updateDateFix);
    window.addEventListener('resize', updateDateFix);
    // 切换 按天聚合/按分钟聚合 标签页时重新绘制并定位到最右侧（面板显示后才量得到宽度）
    var radios = document.querySelectorAll('input[name=scale]');
    for (var ri = 0; ri < radios.length; ri++){
      (function(rd){
        rd.addEventListener('change', function(){
          setTimeout(function(){
            if (chkOn('s-min')) applyBm(); else applyDagg();
          }, 0);
        });
      })(radios[ri]);
    }
    // 性能：首屏只渲染当前可见的标签（最快出图），另一个标签放到后台慢慢渲染；
    // 之后切换标签/改组距/勾选框时，参数没变的重绘由 renderChart 内部短路
    if (chkOn('s-min')){ applyBm(); setTimeout(applyDagg, 60); }
    else { applyDagg(); setTimeout(applyBm, 60); }
    scrollChartsRight();
    // 加载完成后再校验一次（宽度没变则 renderChart 内部短路，几乎零开销）
    window.addEventListener('load', function(){ applyBm(); applyDagg(); });
  } catch (err) {
    if (window.console) console.log('chart js error', err);
  }
})();
"""


def build_weekday_map(minutes):
    """日期 -> 星期（0=周日 … 6=周六），供页面「星期底色」使用。

    星期由 Python 标准库 ``calendar``（万年历算法，与系统时区/本地设置无关）算出，
    覆盖数据首尾之间的**每一天**（不只是有记录的日期），这样任何组距下数据桶的
    起始日期都一定能在表里查到。内嵌成 ``window.WEEKDAY={"20260926":5,…}`` 交给前端。
    """
    if not minutes:
        return {}
    keys = sorted(minutes)
    try:
        first = datetime.datetime.strptime(keys[0][:8], "%Y%m%d").date()
        last = datetime.datetime.strptime(keys[-1][:8], "%Y%m%d").date()
    except ValueError:
        return {}
    out = {}
    step = datetime.timedelta(days=1)
    day = first
    while day <= last:
        # calendar.weekday(): 0=周一 … 6=周日；页面的图例顺序是「周日为每星期第一天」，故 +1 取模后
        # 0=周日、1=周一 … 6=周六，正好对应 WD_FILL 的 红橙黄绿青蓝紫。
        out[day.strftime("%Y%m%d")] = (calendar.weekday(day.year, day.month, day.day) + 1) % 7
        day += step
    return out


def card(key, value, note=""):
    note_html = " <small>%s</small>" % html.escape(note) if note else ""
    return (
        '<div class="card"><div class="k">%s</div>'
        '<div class="v">%s%s</div></div>'
        % (html.escape(key), value, note_html)
    )


def build_html(data, generated_at, summary_path, raw_path):
    parts = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="zh-CN">')
    parts.append("<head>")
    parts.append('<meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    parts.append("<title>小狼毫统计</title>")
    parts.append("<style>%s</style>" % CSS)
    parts.append("</head>")
    parts.append('<body><div class="wrap">')
    parts.append('<h1 id="ttl">输入统计</h1>')

    days_map = data["days"]                       # 日汇总（权威，= ii 弹窗数字）
    minutes = data["minutes"]
    raw_days = aggregate(minutes, 8)
    wd_map = build_weekday_map(minutes)            # 日期->星期（calendar 万年历），供「星期底色」

    # 每日以汇总为准（保证与 ii 弹窗一致）；分钟级只在汇总缺失时补位
    day_map = dict(raw_days)
    day_map.update(days_map)

    # 图表：把缺口补 0 成连续时间轴（仅渲染，不写回数据文件），横轴照常显示没打字的时段
    dayagg_points = continuous(raw_days, "day", MAX_POINTS["day"])
    minute_points = continuous(minutes, "minute", MAX_POINTS["minute"])
    # 卡片/汇总仍用「有数据」的观测值，避免被补 0 的空档拉低
    day_obs = [(k, day_map[k][0], day_map[k][1]) for k in sorted(day_map)]

    cards = []
    today = datetime.date.today().strftime("%Y%m%d")
    if today in day_map:
        cards.append(
            card(
                "今天",
                "%s <small>字 / %s 键</small>"
                % (fmt(day_map[today][0]), fmt(day_map[today][1])),
            )
        )
    else:
        cards.append(card("今天", "<small>尚未记录</small>"))
    cards.append(card("记录天数", fmt(len(day_map)), "天"))
    cards.append(card("累计上屏", fmt(data["total_words"]), "字"))
    cards.append(card("累计按键", fmt(data["total_keys"]), "键"))
    # 2026-10-24：按要求删掉「日均上屏」「日均按键」两张卡片（连同它们的计算代码），
    # 其余卡片（今天 / 记录天数 / 累计上屏 / 累计按键 / 分钟级记录）不变。
    cards.append(card("分钟级记录", fmt(len(minutes)), "条"))
    parts.append('<div class="cards">%s</div>' % "".join(cards))

    parts.append('<div class="tabs">')
    parts.append('<input type="radio" name="scale" id="s-dagg" checked>')
    parts.append('<input type="radio" name="scale" id="s-min">')
    parts.append('<div class="tabbar">')
    parts.append('<label for="s-dagg">按天聚合</label>')
    parts.append('<label for="s-min">按分钟聚合</label>')
    parts.append("</div>")

    # 按天聚合面板：可滚动 + 组距可输入（JS 渲染；无 JS 时按 1 天静态 SVG 兜底）
    min_raw = json.dumps(
        [[key, w, kk] for key, (w, kk) in sorted(minutes.items())], separators=(",", ":")
    )
    dagbody = []
    dagbody.append('<div class="chartcard">')       # 白卡片：组距那一行 + 图表都在里面
    dagbody.append('<div class="minctl">')
    dagbody.append('<span class="minctl-label">组距：</span>')
    # 只保留可输入的组距框（下拉候选列表已按要求删除），直接输数字后回车或点「绘图」
    dagbody.append(
        '<input id="dInput" class="bm-input" type="number" min="1" max="365" step="1" '
        'value="1" placeholder="1-365">'
    )
    dagbody.append('<button type="button" id="dApply" class="bkt">绘图</button>')
    dagbody.append('<span id="dHint" class="minctl-hint"></span>')
    dagbody.append('<span id="dDensityLabel" class="minctl-label"></span>')
    dagbody.append("</div>")
    dagbody.append('<div class="minwrap">')
    dagbody.append('<div class="scroll" id="dScroll">')
    dagg_svg = build_svg(dayagg_points, lab_day, time_day)
    dagg_svg = dagg_svg.replace('<svg class="chart"', '<svg id="dagsvg" class="chart"', 1)
    dagbody.append(dagg_svg)
    dagbody.append("</div>")
    dagbody.append('<div class="yax yax-l" id="yaxL2"></div>')
    dagbody.append('<div class="yax yax-r" id="yaxR2"></div>')
    dagbody.append("</div>")
    dagbody.append("</div>")                       # /chartcard
    dagbody.append('<div class="opts">')
    dagbody.append(
        '<label class="chk"><input type="checkbox" id="dAvgChk" '
        'title="平均值=当前显示数据的平均值（含显示中的 0 值点）"> 平均线</label>'
    )
    dagbody.append(
        '<label class="chk"><input type="checkbox" id="dWdChk" checked '
        'title="按数据点覆盖日期的星期给绘图区背景上色（半透明）"> 星期底色</label>'
    )
    dagbody.append(
        '<span class="chk thr">隐藏'
        '<input id="dThresh" class="thr-in" type="number" min="-1" step="1" value="0" '
        'title="整数、最小 -1：0=隐藏 0 值（默认）；-1=不隐藏任何点；'
        '正数=只显示所选数值高于该值的数据点">'
        "及以下的"
        '<button type="button" id="dThMetric" class="thr-btn" data-metric="words" '
        'title="点击切换筛选所依据的数值：上屏字数 ↔ 按键次数（可反复点击切换）">'
        "上屏字数</button>"
        '<span id="dThHint" class="minctl-hint"></span></span>'
    )
    dagbody.append("</div>")
    parts.append('<div class="pane pane-dagg">%s</div>' % "".join(dagbody))

    # 按分钟聚合面板：可滚动 + 组距可输入（JS 渲染；无 JS 时显示静态 SVG 兜底）
    mbody = []
    mbody.append('<div class="chartcard">')
    mbody.append('<div class="minctl">')
    mbody.append('<span class="minctl-label">组距：</span>')
    # 只保留可输入的组距框（下拉候选列表已按要求删除）
    mbody.append(
        '<input id="bmInput" class="bm-input" type="number" min="1" max="1440" step="1" '
        'value="1" placeholder="1-1440">'
    )
    mbody.append('<button type="button" id="bmApply" class="bkt">绘图</button>')
    mbody.append('<span id="bmHint" class="minctl-hint"></span>')
    mbody.append('<span id="minDensityLabel" class="minctl-label"></span>')
    mbody.append("</div>")
    mbody.append('<div class="minwrap">')
    mbody.append('<div class="scroll" id="minScroll">')
    fallback_svg = build_svg(minute_points, lab_minute, time_minute, date_fn=date_minute)
    fallback_svg = fallback_svg.replace('<svg class="chart"', '<svg id="minsvg" class="chart"', 1)
    mbody.append(fallback_svg)
    mbody.append("</div>")
    mbody.append('<div class="yax yax-l" id="yaxL"></div>')
    mbody.append('<div class="yax yax-r" id="yaxR"></div>')
    mbody.append('<div class="datefix" id="dateFix"></div>')
    mbody.append("</div>")
    mbody.append("</div>")                         # /chartcard
    mbody.append('<div class="opts">')
    mbody.append(
        '<label class="chk"><input type="checkbox" id="mAvgChk" '
        'title="平均值=当前显示数据的平均值（含显示中的 0 值点）"> 平均线</label>'
    )
    mbody.append(
        '<label class="chk"><input type="checkbox" id="mWdChk" checked '
        'title="按数据点覆盖日期的星期给绘图区背景上色（半透明）"> 星期底色</label>'
    )
    mbody.append(
        '<span class="chk thr">隐藏'
        '<input id="minThresh" class="thr-in" type="number" min="-1" step="1" value="0" '
        'title="整数、最小 -1：0=隐藏 0 值（默认）；-1=不隐藏任何点；'
        '正数=只显示所选数值高于该值的数据点">'
        "及以下的"
        '<button type="button" id="minThMetric" class="thr-btn" data-metric="words" '
        'title="点击切换筛选所依据的数值：上屏字数 ↔ 按键次数（可反复点击切换）">'
        "上屏字数</button>"
        '<span id="minThHint" class="minctl-hint"></span></span>'
    )
    mbody.append("</div>")
    parts.append('<div class="pane pane-min">%s</div>' % "".join(mbody))
    parts.append("</div>")

    # 频数分布直方图栏目（「每日明细数据」上方）：由 JS 绘制，数据=当前标签页折线图同一批时间桶
    hbody = []
    hbody.append('<div class="histsec">')
    hbody.append('<div class="minctl">')
    hbody.append('<span class="minctl-label">组距：</span>')
    hbody.append(
        '<input id="hBin" class="bm-input" type="number" min="1" step="1" value="1" '
        'placeholder="1-">'
    )
    hbody.append('<button type="button" id="hApply" class="bkt">绘图</button>')
    hbody.append("</div>")
    hbody.append('<svg id="hsvg" class="chart"></svg>')
    hbody.append("</div>")
    parts.append("".join(hbody))

    if day_obs:
        parts.append("<details>")
        parts.append("<summary>每日明细数据（共%d天）</summary>" % len(day_obs))
        parts.append("<table>")
        parts.append("<tr><th>日期</th><th>上屏字数</th><th>按键次数</th></tr>")
        for key, w, k in reversed(day_obs):
            parts.append(
                "<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
                % (time_day(key), fmt(w), fmt(k))
            )
        parts.append("</table>")
        parts.append("</details>")

    foot = []
    foot.append("生成时间：%s" % html.escape(generated_at))
    if data["start_iso"]:
        foot.append("统计起始：%s" % html.escape(data["start_iso"]))
    foot.append("日汇总文件：%s" % html.escape(summary_path))
    foot.append("分钟级原始文件夹：%s（每月一个 txt）" % html.escape(raw_dir_of(raw_path)))
    foot.append(
        "1分钟采样间隔的数据在早期有部分缺失，造成不同粒度的数据时间范围略有不一致。已考虑修复"
    )
    foot.append(
        "刷新网页没用的，要重新运行 <code>查看每日统计.bat</code> "
        "<code>python plot_input_count.py</code>。"
    )
    parts.append('<div class="foot">%s</div>' % "<br>".join(foot))
    parts.append('<div id="tt" class="tooltip"></div>')
    # 设置面板（点左上角标题「输入统计」打开）：三个输入框各自的滚轮增量 + 纵轴顶端刻度行为
    parts.append('<div id="setMask" class="setmask"></div>')
    parts.append(
        '<div id="setPanel" class="setpanel" role="dialog" aria-label="设置">'
        '<div class="set-hd"><span>设置</span>'
        '<button type="button" id="setClose" class="set-x" title="关闭">×</button></div>'
        '<div class="set-bd">'
        '<div class="set-sec">滚轮增量</div>'
        '<div class="set-row"><span class="set-lb">折线图组距</span>'
        '<input id="cfgBw" class="set-num" type="number" min="1" step="1" value="10">'
        '<label class="chk"><input type="checkbox" id="cfgBwAuto"> 自适应</label></div>'
        '<div class="set-row"><span class="set-lb">隐藏 m 及以下</span>'
        '<input id="cfgThr" class="set-num" type="number" min="1" step="1" value="10" disabled>'
        '<label class="chk"><input type="checkbox" id="cfgThrAuto" checked> 自适应</label></div>'
        '<div class="set-row"><span class="set-lb">直方图组距</span>'
        '<input id="cfgHist" class="set-num" type="number" min="1" step="1" value="10">'
        '<label class="chk"><input type="checkbox" id="cfgHistAuto"> 自适应</label></div>'
        '<div class="set-sec">纵轴</div>'
        '<div class="set-row"><span class="set-lb">点最顶上数字</span>'
        '<label class="chk"><input type="radio" name="ytop" id="cfgYHalf" checked> 减半</label>'
        '<label class="chk"><input type="radio" name="ytop" id="cfgYStep"> 下移一格</label>'
        '</div></div></div>'
    )
    # 按键明细面板：单击数据点后在右侧宽大面板里显示（可滚动）；拖顶部移动、拖右下角调长宽
    parts.append(
        '<div id="klPanel" class="klpanel" role="dialog" aria-label="按键明细">'
        '<div class="klpanel-hd" id="klPanelHd" title="拖动可移动面板位置">'
        '<span id="klPanelTitle">按键明细</span>'
        '<button type="button" id="klPanelClose" class="klpanel-x" title="关闭">×</button></div>'
        '<div class="klpanel-bd" id="klPanelBody"></div>'
        '<div class="klpanel-rz" id="klPanelRz" title="拖动可调整面板长宽"></div></div>'
    )
    parts.append("<script>window.WEEKDAY=%s;</script>" % json.dumps(wd_map, separators=(",", ":"), sort_keys=True))
    parts.append("<script>window.MIN_RAW=%s;</script>" % min_raw)
    parts.append("<script>%s</script>" % CHART_JS)
    parts.append("</div></body></html>")
    doc = "\n".join(parts)
    # 主题色占位符统一替换（CSS / JS / 静态兜底 SVG 全走这里，保证同色）
    return doc.replace("__CW__", COLOR_WORDS).replace("__CK__", COLOR_KEYS)


def try_png(data, html_path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    day_map = dict(aggregate(data["minutes"], 8))
    day_map.update(data["days"])   # 汇总为准
    keys = sorted(day_map)
    xs = [datetime.datetime.strptime(k, "%Y%m%d") for k in keys]
    ws = [day_map[k][0] for k in keys]
    ks = [day_map[k][1] for k in keys]

    fig, ax1 = plt.subplots(figsize=(12, 4.5))
    ax1.plot(xs, ws, color=COLOR_WORDS, marker="o", lw=2, label="上屏字数")
    ax1.set_ylabel("上屏字数", color=COLOR_WORDS)
    ax1.tick_params(axis="y", labelcolor=COLOR_WORDS)
    ax2 = ax1.twinx()
    ax2.plot(xs, ks, color=COLOR_KEYS, ls="--", marker="s", lw=1.8, label="按键数")
    ax2.set_ylabel("按键数", color="#d97706")
    ax2.tick_params(axis="y", labelcolor="#d97706")
    ax1.set_title("每日输入统计")
    fig.autofmt_xdate(rotation=45)
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc="upper left")
    fig.tight_layout()
    png_path = os.path.splitext(html_path)[0] + ".png"
    fig.savefig(png_path, dpi=120)
    plt.close(fig)
    return png_path


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Generate a day/by-day/by-minute line chart (HTML) from Rime input data."
    )
    ap.add_argument("--input", default=DEFAULT_SUMMARY, help="path to input_count.txt (daily summary)")
    ap.add_argument("--raw", default=DEFAULT_RAW, help="path to input_count_raw.txt (minute raw)")
    ap.add_argument("--output", default=DEFAULT_OUTPUT, help="path of HTML chart to write")
    ap.add_argument("--png", action="store_true",
                    help="also save PNG if matplotlib is installed (optional, day scale)")
    args = ap.parse_args(argv)

    summary = parse_summary(args.input)
    migrate_legacy_raw(args.raw)      # 旧版单文件 -> 按月文件（只做一次，旧文件留 .bak）
    raw_minutes = parse_raw(args.raw)
    missing = (summary is None) and (not raw_minutes)
    if summary is None:
        summary = {"start_iso": "", "total_words": 0, "total_keys": 0, "days": {}}
        print("NOTE: summary file not found: %s" % args.input)
    if not raw_minutes:
        print("NOTE: raw file not found or empty: %s" % args.raw)

    day_map = dict(aggregate(raw_minutes, 8))
    day_map.update(summary["days"])   # 汇总为准
    total_w = summary["total_words"]
    total_k = summary["total_keys"]
    if total_w == 0 and total_k == 0:
        total_w = sum(v[0] for v in day_map.values())
        total_k = sum(v[1] for v in day_map.values())
    data = {
        "start_iso": summary["start_iso"],
        "total_words": total_w,
        "total_keys": total_k,
        "minutes": raw_minutes,
        "days": summary["days"],
    }
    summary_path, raw_path = args.input, args.raw
    if missing:
        print("NOTE: no data files yet - chart will show empty state")

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    doc = build_html(data, now, summary_path, raw_path)

    try:
        out_dir = os.path.dirname(os.path.abspath(args.output))
        if out_dir and not os.path.isdir(out_dir):
            os.makedirs(out_dir)
        with open(args.output, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(doc)
    except OSError as exc:
        print("ERROR: cannot write %s: %s" % (args.output, exc))
        return 1

    ensure_keylog_helper()   # 图表页「单击看按键 / 双击开副本」需要本地小服务

    size = os.path.getsize(args.output)
    print("OK: %d minute bucket(s) -> %s" % (len(data["minutes"]), args.output))
    print("OK: chart written: %s (%d bytes)" % (args.output, size))
    if size < 500:
        print("WARN: chart file looks too small")
        return 1

    if args.png:
        if not (data["minutes"] or data["days"]):
            print("SKIP: no data, no PNG")
        else:
            try:
                png_path = try_png(data, args.output)
                print("OK: PNG written: %s" % png_path)
            except ImportError:
                print("SKIP: matplotlib not installed, no PNG generated")
            except Exception as exc:
                print("WARN: PNG generation failed: %s" % exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
