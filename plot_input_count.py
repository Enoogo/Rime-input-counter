#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""plot_input_count.py - 生成 Rime（小狼毫）输入统计折线图（可切换 每日/按天聚合/按分钟聚合 尺度）。

数据源::

    input_count.txt        日汇总（权威）：start_iso / total_* / day=YYYYMMDD day_words=N day_keys=N
    input_count_raw.txt    分钟级原始：e=YYYYMMDDHHMM w=<字数> k=<按键数>

尺度口径：
  * 每日  —— 以 input_count.txt 的 day= 行为准（与 ii 弹窗显示的数字完全一致）。
  * 按天聚合/按分钟聚合（原「每小时」「详细图」标签） —— 由 input_count_raw.txt 聚合
    （细粒度，但只含开始记录分钟级之后的数据）。组距均可在页面上输入：分钟 1–1440、天 1–365。

用法::

    python plot_input_count.py                     # -> input_count_chart.html
    python plot_input_count.py --demo              # 合成示例数据演示图
    python plot_input_count.py --png               # 可选 PNG（需 matplotlib，按日尺度）
"""

import argparse
import datetime
import html
import json
import math
import os
import random
import re
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SUMMARY = os.path.join(BASE_DIR, "input_count.txt")
DEFAULT_RAW = os.path.join(BASE_DIR, "input_count_raw.txt")
DEFAULT_OUTPUT = os.path.join(BASE_DIR, "input_count_chart.html")

DAY_RE = re.compile(r"^\s*day=(\d{8})\s+day_words=(-?\d+)\s+day_keys=(-?\d+)\s*$")
TOTAL_RE = re.compile(r"^\s*total_words=(-?\d+)\s+total_keys=(-?\d+)\s*$")
START_RE = re.compile(r"^\s*start_iso=(\S.*)$")
RAW_RE = re.compile(r"^\s*e=(\d{12})\s+w=(-?\d+)\s+k=(-?\d+)\s*$")

COLOR_WORDS = "#2563eb"
COLOR_KEYS = "#f59e0b"

# 仅限制「无 JS 时静态兜底 SVG」的最长点数；页面实际图表由 JS 绘制，画出全部数据点
MAX_POINTS = {"day": 365, "minute": 300}


def fmt(n):
    try:
        return "{:,}".format(int(n))
    except (TypeError, ValueError):
        return str(n)


def fmt1(x):
    """保留 1 位小数、千分位（去零平均线的数值标注）。"""
    try:
        return "{:,.1f}".format(float(x))
    except (TypeError, ValueError):
        return str(x)


def avg_nonzero(points):
    """去零平均值：上屏字数、按键次数各自剔除 0 值后求平均（无非零值时返回 0）。"""
    ws = [p[1] for p in points if p[1] > 0]
    ks = [p[2] for p in points if p[2] > 0]
    return (
        (sum(ws) / float(len(ws))) if ws else 0.0,
        (sum(ks) / float(len(ks))) if ks else 0.0,
    )


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


def parse_raw(path):
    """解析分钟级原始 input_count_raw.txt（每分钟一行）+ input_count_raw.tmp（当前分钟流水）。
    返回 {minutekey: (w, k)}（同分钟求和）。"""
    minutes = {}
    if not os.path.isfile(path):
        return minutes
    tmp_path = os.path.splitext(path)[0] + ".tmp"
    for src in (path, tmp_path):
        if not os.path.isfile(src):
            continue
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


def aggregate(minutes, width):
    acc = {}
    for key, (w, k) in minutes.items():
        b = key[:width]
        if b in acc:
            acc[b] = (acc[b][0] + w, acc[b][1] + k)
        else:
            acc[b] = (w, k)
    return acc


def window(points, scale):
    m = MAX_POINTS[scale]
    return points[-m:] if len(points) > m else points


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


def build_svg(points, label_fn, time_fn, date_fn=None, avg=False):
    """双纵轴折线图 SVG。points: [(key, w, k)]。含可视点 + 悬停命中区（JS 提示框）。

    date_fn 可选：返回非空字符串的点视为「新的一天 0:00」，在其正下方标注日期
    （该日期覆盖此点以右的数据），并画一条浅色日分隔线。
    横轴时刻刻度按实际文本宽度自动定步长，任何组距都绝不重叠。
    avg=True 时绘制「去零平均线」（字=蓝虚线、键=橙虚线，默认隐藏，由勾选框切换）。
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

    # 日分隔线 + 日期标注（每天 0:00 的数据点正下方 = 此点以右当天数据的日期）
    if date_fn:
        for i, (key, w, k) in enumerate(points):
            dlab = date_fn(key)
            if not dlab:
                continue
            x = x_at(i)
            out.append(
                '<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#d1d5db" '
                'stroke-width="1" stroke-dasharray="3 4"/>' % (x, mt, x, mt + ph)
            )
            out.append(
                '<text x="%.1f" y="%d" class="xl xd" text-anchor="middle">%s</text>'
                % (x, y_date, html.escape(dlab))
            )

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
        'stroke-dasharray="6 4" stroke-linejoin="round"/>' % (kpts, COLOR_KEYS)
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

    # 去零平均线（字=蓝虚线、键=橙虚线，默认 display:none，由勾选框显示/隐藏）
    if avg and n:
        avg_w, avg_k = avg_nonzero(points)
        if avg_w > 0:
            y = y_at(avg_w, wmax)
            out.append(
                '<line class="avgline" style="display:none" x1="%d" y1="%.1f" x2="%d" y2="%.1f" '
                'stroke="%s" stroke-width="1.5" stroke-dasharray="3 3"/>'
                % (ml, y, ml + pw, y, COLOR_WORDS)
            )
            out.append(
                '<text class="avglab avgline" style="display:none" x="%d" y="%.1f" fill="%s">字去零平均 %s</text>'
                % (ml + 8, y - 4, COLOR_WORDS, fmt1(avg_w))
            )
        if avg_k > 0:
            y = y_at(avg_k, kmax)
            out.append(
                '<line class="avgline" style="display:none" x1="%d" y1="%.1f" x2="%d" y2="%.1f" '
                'stroke="%s" stroke-width="1.5" stroke-dasharray="3 3"/>'
                % (ml, y, ml + pw, y, COLOR_KEYS)
            )
            out.append(
                '<text class="avglab avgline" style="display:none" x="%d" y="%.1f" fill="%s">键去零平均 %s</text>'
                % (ml + 8, y - 4, COLOR_KEYS, fmt1(avg_k))
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
    out.append('<text x="%d" y="29" class="legend">上屏字数（左轴）</text>' % (ml + 36))
    out.append(
        '<line x1="%d" y1="24" x2="%d" y2="24" stroke="%s" stroke-width="3" '
        'stroke-dasharray="6 4"/>' % (ml + 190, ml + 218, COLOR_KEYS)
    )
    out.append('<text x="%d" y="29" class="legend">按键数（右轴）</text>' % (ml + 226))

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
svg.chart { width: 100%; height: auto; display: block; }
svg.chart text { font-family: "Segoe UI", "Microsoft YaHei", sans-serif; }
.yl { font-size: 11px; fill: #6b7280; }
.yl-left { fill: #2563eb; }
.yl-right { fill: #d97706; }
.xl { font-size: 11px; fill: #6b7280; }
.xd { fill: #4b5563; font-weight: 600; }
.legend { font-size: 13px; fill: #374151; }
.axis-title { font-size: 12px; fill: #9ca3af; }
details { margin-top: 14px; }
summary { cursor: pointer; color: #2563eb; font-size: 14px; }
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
.note { color: #6b7280; font-size: 12px; margin-top: 10px; line-height: 1.7; }
.tabs input[type=radio] { position: absolute; opacity: 0; pointer-events: none; }
.tabbar { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.tabbar label { cursor: pointer; padding: 8px 18px; border: 1px solid #e5e7eb;
  border-radius: 8px; background: #fff; color: #374151; font-size: 13px; }
#s-day:checked ~ .tabbar label[for="s-day"],
#s-dagg:checked ~ .tabbar label[for="s-dagg"],
#s-min:checked ~ .tabbar label[for="s-min"] {
  background: #2563eb; color: #fff; border-color: #2563eb; }
.pane { display: none; }
#s-day:checked ~ .pane-day,
#s-dagg:checked ~ .pane-dagg,
#s-min:checked ~ .pane-min { display: block; }
circle.hit { fill: rgba(0,0,0,0); pointer-events: all; cursor: pointer; }
.minctl { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.minctl .minctl-label { font-size: 13px; color: #6b7280; }
.bm-input { width: 88px; padding: 6px 8px; border: 1px solid #e5e7eb; border-radius: 6px;
  font-size: 13px; color: #111827; background: #fff; }
.bm-input:focus { outline: none; border-color: #2563eb; }
.bkt { cursor: pointer; padding: 6px 14px; border: 1px solid #2563eb; border-radius: 6px;
  background: #2563eb; color: #fff; font-size: 12px; }
.bkt:hover { background: #1d4ed8; }
.minctl-hint { font-size: 12px; color: #b45309; }
.minwrap { position: relative; }
.scroll { overflow-x: auto; overflow-y: hidden; border: 1px solid #f1f5f9; border-radius: 8px;
  padding-bottom: 6px; }
/* 固定的纵轴刻度 */
.yax { position: absolute; top: 0; width: 78px; height: 431px; pointer-events: none;
  border-radius: 8px 8px 0 0; }
.yax-l { left: 0; background: linear-gradient(to right, #fff 62%, rgba(255,255,255,0)); }
.yax-r { right: 0; background: linear-gradient(to left, #fff 62%, rgba(255,255,255,0)); }
.yax .yt { position: absolute; transform: translateY(-50%); font-size: 11px;
  font-variant-numeric: tabular-nums; white-space: nowrap; }
.yax-l .yt { right: 10px; text-align: right; }
.yax-r .yt { left: 10px; }
.yt-l { color: #2563eb; }
.yt-r { color: #d97706; }
.yt-title { font-size: 12px; color: #9ca3af; }
/* 滚动后看不到 0:00 时，固定在左下角（左侧纵轴下方）的日期 */
.datefix { position: absolute; left: 3px; top: 412px; z-index: 4; display: none;
  background: #fff; border: 1px solid #d1d5db; border-radius: 6px; padding: 1px 6px;
  font-size: 11px; font-weight: 600; color: #374151; white-space: nowrap;
  font-variant-numeric: tabular-nums; pointer-events: none;
  box-shadow: 0 1px 3px rgba(0,0,0,0.10); }
#minsvg, #dagsvg { display: block; }
.scroll-hint { color: #9ca3af; font-size: 12px; margin-top: 6px; }
.chk { display: flex; align-items: center; gap: 7px; font-size: 13px; color: #374151;
  margin-top: 8px; cursor: pointer; user-select: none; }
.chk input { width: 15px; height: 15px; accent-color: #2563eb; cursor: pointer; }
.avglab { font-size: 10px; }
.tooltip { position: fixed; z-index: 100; display: none; background: #1f2937; color: #f9fafb;
  padding: 10px 12px; border-radius: 8px; font-size: 13px; line-height: 1.7;
  box-shadow: 0 6px 20px rgba(0,0,0,0.28); pointer-events: none; white-space: nowrap; }
.tooltip .tt-time { font-weight: 600; color: #fff; margin-bottom: 4px; }
.tooltip .tt-row { display: flex; align-items: center; gap: 7px; }
.tooltip .tt-sw, .tooltip .tt-sk { width: 11px; height: 11px; border-radius: 3px; display: inline-block; }
.tooltip .tt-sw { background: #2563eb; }
.tooltip .tt-sk { background: #f59e0b; }
.tooltip .tt-row b { margin-left: auto; padding-left: 16px; font-variant-numeric: tabular-nums; }
.tooltip .tt-empty { color: #9ca3af; font-size: 12px; margin-top: 4px; }
"""

CHART_JS = """
(function(){
  var tt = document.getElementById('tt');
  function show(el, e){
    if(!tt) return;
    var w = el.getAttribute('data-w'), k = el.getAttribute('data-k');
    var extra = (w === '0' && k === '0') ? '<div class="tt-empty">这段时间你一个字没打</div>' : '';
    tt.innerHTML = '<div class="tt-time">'+el.getAttribute('data-label')+'</div>'
      + '<div class="tt-row"><span class="tt-sw"></span>上屏字数<b>'+w+'</b></div>'
      + '<div class="tt-row"><span class="tt-sk"></span>按键次数<b>'+k+'</b></div>'
      + extra;
    tt.style.display = 'block';
    move(e);
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
  document.addEventListener('mouseover', function(e){ if(isHit(e.target)) show(e.target, e); });
  document.addEventListener('mousemove', function(e){ if(tt && tt.style.display === 'block') move(e); });
  document.addEventListener('mouseout', function(e){ if(isHit(e.target)) hide(); });

  function pad(n){ return (n < 10 ? '0' : '') + n; }
  function fmtN(n){ return Number(n).toLocaleString(); }
  function fmt1(x){ return Number(x).toLocaleString(undefined, {maximumFractionDigits: 1}); }
  function chkOn(id){ var c = document.getElementById(id); return !!(c && c.checked); }
  // 去零平均：上屏字数、按键次数各自剔除 0 值后求平均（无非零值返回 0）
  function avgNZ(pts, idx){
    var s = 0, c = 0;
    for (var ai = 0; ai < pts.length; ai++){ if (pts[ai][idx] > 0){ s += pts[ai][idx]; c++; } }
    return c ? s / c : 0;
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

  function renderMin(bm){
    var svg = document.getElementById('minsvg');
    if(!svg) return;
    var raw = window.MIN_RAW || [];
    if(!raw.length){ MIN_PTS = null; updateDateFix(); return; }
    var bms = bm * 60000, acc = {}, minB = Infinity, maxB = -Infinity, i;
    var perDay = Math.ceil(1440 / bm);   // 每天的组数（每天最后一组可能不足 bm 分钟）
    for (i = 0; i < raw.length; i++){
      var d0 = keyDate(raw[i][0]);
      var dn = dayNumber(d0);
      var slot = Math.floor((d0.getTime() - dayStartMs(dn)) / bms);
      if (slot > perDay - 1) slot = perDay - 1;
      var b = dn * perDay + slot;
      if (!acc[b]) acc[b] = [0, 0];
      acc[b][0] += raw[i][1]; acc[b][1] += raw[i][2];
      if (b < minB) minB = b;
      if (b > maxB) maxB = b;
    }
    var pts = [];
    for (var b2 = minB; b2 <= maxB; b2++){
      var v = acc[b2] || [0, 0];
      var dn2 = Math.floor(b2 / perDay), slot2 = b2 - dn2 * perDay;
      pts.push([new Date(dayStartMs(dn2) + slot2 * bms), v[0], v[1]]);
    }
    // 「删去0值」勾选框：勾选后不绘制 0 值点（字、键均为 0 的点），
    // 只把不为 0 的数据按时间顺序绘制出来，横轴时刻刻度/日期标注随之只标剩余的点。
    var dz = chkOn('minDropZero');
    if (dz){
      var fz = [];
      for (i = 0; i < pts.length; i++){
        if (pts[i][1] !== 0 || pts[i][2] !== 0) fz.push(pts[i]);
      }
      pts = fz;
    }
    if (!pts.length){ svg.innerHTML = ''; MIN_PTS = null; updateDateFix(); return; }
    var n = pts.length;
    var SP = 9, H = 430, ml = 78, mr = 78, mt = 58, mb = 64;
    // 宽度至少填满滚动容器可见区，保证左右固定纵轴贴着图表两侧
    var cw = (svg.parentNode && svg.parentNode.clientWidth) ? svg.parentNode.clientWidth : 0;
    var W = Math.max(n * SP + ml + mr, cw, 360);
    var pw = W - ml - mr, ph = H - mt - mb;
    var mw = 0, mk = 0, iw = 0, ik = 0;
    for (i = 0; i < n; i++){
      if (pts[i][1] > mw){ mw = pts[i][1]; iw = i; }
      if (pts[i][2] > mk){ mk = pts[i][2]; ik = i; }
    }
    var wmax = niceMax(mw), kmax = niceMax(mk);
    function X(j){ return ml + (n <= 1 ? pw * 0.5 : pw * j / (n - 1)); }
    function Y(v, vm){ return mt + ph * (1 - v / vm); }
    var s = [];
    var yl = [], yr = [];
    for (var g = 0; g <= 5; g++){
      var fr = g / 5, y = mt + ph * (1 - fr);
      s.push('<line x1="'+ml+'" y1="'+y.toFixed(1)+'" x2="'+(ml+pw)+'" y2="'+y.toFixed(1)+'" stroke="#e5e7eb" stroke-width="1"/>');
      yl.push('<span class="yt yt-l" style="top:'+(y+1).toFixed(1)+'px">'+fmtN(Math.round(wmax*fr))+'</span>');
      yr.push('<span class="yt yt-r" style="top:'+(y+1).toFixed(1)+'px">'+fmtN(Math.round(kmax*fr))+'</span>');
    }
    yl.push('<span class="yt yt-l yt-title" style="top:'+(mt-11)+'px">字</span>');
    yr.push('<span class="yt yt-r yt-title" style="top:'+(mt-11)+'px">键</span>');
    // 纵轴刻度固定显示在滚动区左右两侧，不随图表横向滚动
    var boxL = document.getElementById('yaxL'), boxR = document.getElementById('yaxR');
    if (boxL) boxL.innerHTML = yl.join('');
    if (boxR) boxR.innerHTML = yr.join('');
    s.push('<line x1="'+ml+'" y1="'+(mt+ph)+'" x2="'+(ml+pw)+'" y2="'+(mt+ph)+'" stroke="#9ca3af" stroke-width="1.2"/>');
    // 日分隔线 + 日期标注：日期画在每天 0:00 数据点的正下方（= 此点以右当天数据的日期）
    var bidx = {}, lastDay = '';
    for (i = 0; i < n; i++){
      var dd = pts[i][0];
      var ds3 = fDate(dd);
      // 正常：日期标在每天 0:00 的点正下方；「删去0值」勾选后 0 点可能被删，
      // 改为标在每天第一个剩下的数据点正下方（横轴标注随删 0 后的数据自动跟随）
      var mark = dz ? (ds3 !== lastDay) : (dd.getHours() === 0 && dd.getMinutes() === 0);
      lastDay = ds3;
      if (mark){
        var x3 = X(i);
        s.push('<line x1="'+x3.toFixed(1)+'" y1="'+mt+'" x2="'+x3.toFixed(1)+'" y2="'+(mt+ph)+'" stroke="#d1d5db" stroke-width="1" stroke-dasharray="3 4"/>');
        s.push('<text x="'+x3.toFixed(1)+'" y="'+(mt+ph+42)+'" class="xl xd" text-anchor="middle">'+ds3+'</text>');
        bidx[ds3] = i;
      }
    }
    // 时刻刻度：步长由实际文本宽度与点距决定，任何组距都不重叠
    var dxp = (n > 1) ? pw / (n - 1) : pw;
    var labW = Math.max(textW('00:00'), textW('12:34'), textW('23:59'));
    // 删 0 后点的时间不再等间隔，时刻标注直接按屏幕空间取步长（标注取自各点真实时间）
    var stride = dz
      ? Math.max(1, Math.ceil((labW + 12) / (dxp || 1)))
      : pickStride(Math.max(1, Math.ceil((labW + 12) / dxp)), bm);
    if (stride > n) stride = n;
    for (i = 0; i < n; i += stride){
      s.push('<text x="'+X(i).toFixed(1)+'" y="'+(mt+ph+22)+'" class="xl" text-anchor="middle">'+fLabel(pts[i][0])+'</text>');
    }
    var wp = [], kp = [];
    for (i = 0; i < n; i++){ wp.push(X(i).toFixed(1) + ',' + Y(pts[i][1], wmax).toFixed(1)); kp.push(X(i).toFixed(1) + ',' + Y(pts[i][2], kmax).toFixed(1)); }
    s.push('<polyline points="'+kp.join(' ')+'" fill="none" stroke="#f59e0b" stroke-width="2" stroke-dasharray="6 4" stroke-linejoin="round"/>');
    s.push('<polyline points="'+wp.join(' ')+'" fill="none" stroke="#2563eb" stroke-width="2.5" stroke-linejoin="round"/>');
    for (i = 0; i < n; i++){
      var x = X(i);
      s.push('<circle cx="'+x.toFixed(1)+'" cy="'+Y(pts[i][2], kmax).toFixed(1)+'" r="3.2" fill="#f59e0b"/>');
      s.push('<circle cx="'+x.toFixed(1)+'" cy="'+Y(pts[i][1], wmax).toFixed(1)+'" r="3.2" fill="#2563eb"/>');
    }
    // 去零平均线（勾选后显示）：字=蓝虚线（左轴高度）、键=橙虚线（右轴高度）
    if (chkOn('mAvgChk')){
      var wav = avgNZ(pts, 1), kav = avgNZ(pts, 2);
      if (wav > 0){
        var ywa = Y(wav, wmax);
        s.push('<line x1="'+ml+'" y1="'+ywa.toFixed(1)+'" x2="'+(ml+pw)+'" y2="'+ywa.toFixed(1)+'" stroke="#2563eb" stroke-width="1.5" stroke-dasharray="3 3"/>');
        s.push('<text x="'+(ml+8)+'" y="'+(ywa-4).toFixed(1)+'" class="avglab" fill="#2563eb">字去零平均 '+fmt1(wav)+'</text>');
      }
      if (kav > 0){
        var yka = Y(kav, kmax);
        s.push('<line x1="'+ml+'" y1="'+yka.toFixed(1)+'" x2="'+(ml+pw)+'" y2="'+yka.toFixed(1)+'" stroke="#f59e0b" stroke-width="1.5" stroke-dasharray="3 3"/>');
        s.push('<text x="'+(ml+8)+'" y="'+(yka-4).toFixed(1)+'" class="avglab" fill="#f59e0b">键去零平均 '+fmt1(kav)+'</text>');
      }
    }
    for (i = 0; i < n; i++){
      var x2 = X(i);
      var at = 'data-label="'+fTip(pts[i][0])+'" data-w="'+fmtN(pts[i][1])+'" data-k="'+fmtN(pts[i][2])+'"';
      s.push('<circle class="hit" cx="'+x2.toFixed(1)+'" cy="'+Y(pts[i][1], wmax).toFixed(1)+'" r="14" '+at+'/>');
      s.push('<circle class="hit" cx="'+x2.toFixed(1)+'" cy="'+Y(pts[i][2], kmax).toFixed(1)+'" r="14" '+at+'/>');
    }
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    svg.setAttribute('width', W); svg.setAttribute('height', H);
    svg.style.width = W + 'px'; svg.style.height = H + 'px';
    svg.innerHTML = s.join('');
    var lbl = document.getElementById('minDensityLabel');
    if (lbl) lbl.textContent = ('每点 ' + bm + ' 分钟 · 共 ' + n + ' 点 · 最高'
      + fmtN(mw) + '字（' + fTip(pts[iw][0]) + '），' + fmtN(mk) + '键（' + fTip(pts[ik][0]) + '）');
    // 供滚动时更新左下角固定日期用
    MIN_N = n; MIN_DX = dxp; MIN_X0 = ml; MIN_PWD = pw; MIN_PTS = pts; MIN_BIDX = bidx;
    // 每次重绘（含切换 1 分钟/…/1440 分钟组距）后都回到最右侧
    scrollChartsRight();
    updateDateFix();
  }

  // 可输入值的组距下拉列表：选项 1/5/10/15/30/60/120/360/720/1440，也允许输入 1–1440 之间的任意整数
  function applyBm(){
    var inp = document.getElementById('bmInput');
    if (!inp){ renderMin(1); return; }
    var hint = document.getElementById('bmHint');
    var v = parseInt(inp.value, 10);
    var msg = '';
    if (isNaN(v)){ v = 1; msg = '请输入 1–1440 之间的整数，已按 1 分钟绘图'; }
    else {
      var c = Math.min(1440, Math.max(1, v));
      if (c !== v){ msg = '输入超出 1–1440 范围，已按 ' + c + ' 分钟绘图'; }
      v = c;
    }
    inp.value = v;
    if (hint) hint.textContent = msg;
    renderMin(v);
  }

  // ---- 按天聚合：每 bw 天（1–365）一个点，按自然日序号整除对齐（数据不随日期漂移） ----
  function renderDayAgg(bw){
    var svg = document.getElementById('dagsvg');
    if(!svg) return;
    var raw = window.MIN_RAW || [];
    if(!raw.length) return;
    var acc = {}, minB = Infinity, maxB = -Infinity, i;
    for (i = 0; i < raw.length; i++){
      var dn = dayNumber(keyDate(raw[i][0]));
      var b = Math.floor(dn / bw);
      if (!acc[b]) acc[b] = [0, 0];
      acc[b][0] += raw[i][1]; acc[b][1] += raw[i][2];
      if (b < minB) minB = b;
      if (b > maxB) maxB = b;
    }
    var pts = [];
    for (var b2 = minB; b2 <= maxB; b2++){
      var v = acc[b2] || [0, 0];
      pts.push([new Date(dayStartMs(b2 * bw)), v[0], v[1]]);
    }
    var n = pts.length;
    var SP = 9, H = 430, ml = 78, mr = 78, mt = 58, mb = 64;
    // 宽度至少填满滚动容器可见区，保证左右固定纵轴贴着图表两侧
    var cw = (svg.parentNode && svg.parentNode.clientWidth) ? svg.parentNode.clientWidth : 0;
    var W = Math.max(n * SP + ml + mr, cw, 360);
    var pw = W - ml - mr, ph = H - mt - mb;
    var mw = 0, mk = 0, iw = 0, ik = 0;
    for (i = 0; i < n; i++){
      if (pts[i][1] > mw){ mw = pts[i][1]; iw = i; }
      if (pts[i][2] > mk){ mk = pts[i][2]; ik = i; }
    }
    var wmax = niceMax(mw), kmax = niceMax(mk);
    function X(j){ return ml + (n <= 1 ? pw * 0.5 : pw * j / (n - 1)); }
    function Y(v, vm){ return mt + ph * (1 - v / vm); }
    var s = [];
    var yl = [], yr = [];
    for (var g = 0; g <= 5; g++){
      var fr = g / 5, y = mt + ph * (1 - fr);
      s.push('<line x1="'+ml+'" y1="'+y.toFixed(1)+'" x2="'+(ml+pw)+'" y2="'+y.toFixed(1)+'" stroke="#e5e7eb" stroke-width="1"/>');
      yl.push('<span class="yt yt-l" style="top:'+(y+1).toFixed(1)+'px">'+fmtN(Math.round(wmax*fr))+'</span>');
      yr.push('<span class="yt yt-r" style="top:'+(y+1).toFixed(1)+'px">'+fmtN(Math.round(kmax*fr))+'</span>');
    }
    yl.push('<span class="yt yt-l yt-title" style="top:'+(mt-11)+'px">字</span>');
    yr.push('<span class="yt yt-r yt-title" style="top:'+(mt-11)+'px">键</span>');
    // 纵轴刻度固定显示在滚动区左右两侧，不随图表横向滚动
    var boxL = document.getElementById('yaxL2'), boxR = document.getElementById('yaxR2');
    if (boxL) boxL.innerHTML = yl.join('');
    if (boxR) boxR.innerHTML = yr.join('');
    s.push('<line x1="'+ml+'" y1="'+(mt+ph)+'" x2="'+(ml+pw)+'" y2="'+(mt+ph)+'" stroke="#9ca3af" stroke-width="1.2"/>');
    // 横轴刻度 = 每点起始日期；步长按实际文本宽度自动稀疏，任何组距都不重叠
    var dxp = (n > 1) ? pw / (n - 1) : pw;
    var labW = Math.max(textW('01-02'), textW('12-31'));
    var stride = Math.max(1, Math.ceil((labW + 12) / (dxp || 1)));
    if (stride > n) stride = n;
    for (i = 0; i < n; i += stride){
      s.push('<text x="'+X(i).toFixed(1)+'" y="'+(mt+ph+22)+'" class="xl" text-anchor="middle">'+fLabelD(pts[i][0])+'</text>');
    }
    var wp = [], kp = [];
    for (i = 0; i < n; i++){ wp.push(X(i).toFixed(1) + ',' + Y(pts[i][1], wmax).toFixed(1)); kp.push(X(i).toFixed(1) + ',' + Y(pts[i][2], kmax).toFixed(1)); }
    s.push('<polyline points="'+kp.join(' ')+'" fill="none" stroke="#f59e0b" stroke-width="2" stroke-dasharray="6 4" stroke-linejoin="round"/>');
    s.push('<polyline points="'+wp.join(' ')+'" fill="none" stroke="#2563eb" stroke-width="2.5" stroke-linejoin="round"/>');
    for (i = 0; i < n; i++){
      var x = X(i);
      s.push('<circle cx="'+x.toFixed(1)+'" cy="'+Y(pts[i][2], kmax).toFixed(1)+'" r="3.2" fill="#f59e0b"/>');
      s.push('<circle cx="'+x.toFixed(1)+'" cy="'+Y(pts[i][1], wmax).toFixed(1)+'" r="3.2" fill="#2563eb"/>');
    }
    // 去零平均线（勾选后显示）：字=蓝虚线（左轴高度）、键=橙虚线（右轴高度）
    if (chkOn('dAvgChk')){
      var wav = avgNZ(pts, 1), kav = avgNZ(pts, 2);
      if (wav > 0){
        var ywa = Y(wav, wmax);
        s.push('<line x1="'+ml+'" y1="'+ywa.toFixed(1)+'" x2="'+(ml+pw)+'" y2="'+ywa.toFixed(1)+'" stroke="#2563eb" stroke-width="1.5" stroke-dasharray="3 3"/>');
        s.push('<text x="'+(ml+8)+'" y="'+(ywa-4).toFixed(1)+'" class="avglab" fill="#2563eb">字去零平均 '+fmt1(wav)+'</text>');
      }
      if (kav > 0){
        var yka = Y(kav, kmax);
        s.push('<line x1="'+ml+'" y1="'+yka.toFixed(1)+'" x2="'+(ml+pw)+'" y2="'+yka.toFixed(1)+'" stroke="#f59e0b" stroke-width="1.5" stroke-dasharray="3 3"/>');
        s.push('<text x="'+(ml+8)+'" y="'+(yka-4).toFixed(1)+'" class="avglab" fill="#f59e0b">键去零平均 '+fmt1(kav)+'</text>');
      }
    }
    for (i = 0; i < n; i++){
      var x2 = X(i);
      var at = 'data-label="'+fTipD(pts[i][0], bw)+'" data-w="'+fmtN(pts[i][1])+'" data-k="'+fmtN(pts[i][2])+'"';
      s.push('<circle class="hit" cx="'+x2.toFixed(1)+'" cy="'+Y(pts[i][1], wmax).toFixed(1)+'" r="14" '+at+'/>');
      s.push('<circle class="hit" cx="'+x2.toFixed(1)+'" cy="'+Y(pts[i][2], kmax).toFixed(1)+'" r="14" '+at+'/>');
    }
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    svg.setAttribute('width', W); svg.setAttribute('height', H);
    svg.style.width = W + 'px'; svg.style.height = H + 'px';
    svg.innerHTML = s.join('');
    var lbl = document.getElementById('dDensityLabel');
    if (lbl) lbl.textContent = ('每点 ' + bw + ' 天 · 共 ' + n + ' 点 · 最高'
      + fmtN(mw) + '字（' + fDate(pts[iw][0]) + '），' + fmtN(mk) + '键（' + fDate(pts[ik][0]) + '）');
    scrollChartsRight();
  }

  // 按天聚合的组距输入：选项 1/2/3/7/14/30/90/180/365，也允许输入 1–365 之间的任意整数
  function applyDagg(){
    var inp = document.getElementById('dInput');
    if (!inp){ renderDayAgg(1); return; }
    var hint = document.getElementById('dHint');
    var v = parseInt(inp.value, 10);
    var msg = '';
    if (isNaN(v)){ v = 1; msg = '请输入 1–365 之间的整数，已按 1 天绘图'; }
    else {
      var c = Math.min(365, Math.max(1, v));
      if (c !== v){ msg = '输入超出 1–365 范围，已按 ' + c + ' 天绘图'; }
      v = c;
    }
    inp.value = v;
    if (hint) hint.textContent = msg;
    renderDayAgg(v);
  }

  // 每日图的去零平均线：静态 SVG 里默认隐藏（display:none），勾选框切换显示
  function toggleDayAvg(){
    var chk = document.getElementById('dayAvgChk');
    var svg = document.getElementById('daysvg');
    if (!chk || !svg) return;
    var els = svg.querySelectorAll('.avgline');
    for (var ti = 0; ti < els.length; ti++){
      els[ti].style.display = chk.checked ? '' : 'none';
    }
  }

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
  try {
    bindCtl('bmInput', 'bmApply', applyBm);
    bindCtl('dInput', 'dApply', applyDagg);
    // 勾选框：去零平均线（每日/按天聚合/按分钟聚合）、分钟级「删去0值」
    var dz0 = document.getElementById('minDropZero');
    if (dz0) dz0.addEventListener('change', applyBm);
    var ma0 = document.getElementById('mAvgChk');
    if (ma0) ma0.addEventListener('change', applyBm);
    var da0 = document.getElementById('dAvgChk');
    if (da0) da0.addEventListener('change', applyDagg);
    var ya0 = document.getElementById('dayAvgChk');
    if (ya0){ ya0.addEventListener('change', toggleDayAvg); toggleDayAvg(); }
    // 横向滚动/窗口尺寸变化时，同步更新左下角固定的日期标注
    var sc0 = document.getElementById('minScroll');
    if (sc0) sc0.addEventListener('scroll', updateDateFix);
    window.addEventListener('resize', updateDateFix);
    // 切换 每日/按天聚合/按分钟聚合 标签页时重新绘制并定位到最右侧（面板显示后才量得到宽度）
    var radios = document.querySelectorAll('input[name=scale]');
    for (var ri = 0; ri < radios.length; ri++){
      (function(rd){
        rd.addEventListener('change', function(){
          setTimeout(function(){
            var smin = document.getElementById('s-min');
            var sdagg = document.getElementById('s-dagg');
            if (smin && smin.checked){ applyBm(); }
            else if (sdagg && sdagg.checked){ applyDagg(); }
            else { scrollChartsRight(); }
          }, 0);
        });
      })(radios[ri]);
    }
    applyBm();     // 按分钟聚合：默认 1 分钟
    applyDagg();   // 按天聚合：默认 1 天
    scrollChartsRight();
    window.addEventListener('load', function(){ applyBm(); applyDagg(); });
  } catch (err) {
    if (window.console) console.log('chart js error', err);
  }
})();
"""


def card(key, value, note=""):
    note_html = " <small>%s</small>" % html.escape(note) if note else ""
    return (
        '<div class="card"><div class="k">%s</div>'
        '<div class="v">%s%s</div></div>'
        % (html.escape(key), value, note_html)
    )


def pane_html(scale_name, scale_label, points, label_fn, time_fn, extra_note="",
              avg=False, avg_chk_id=""):
    if points:
        svg = build_svg(points, label_fn, time_fn, avg=avg)
        if avg_chk_id:
            svg = svg.replace('<svg class="chart"', '<svg id="daysvg" class="chart"', 1)
        body = '<div class="panel">%s</div>' % svg
    else:
        body = (
            '<div class="panel"><div class="empty">'
            "<p><strong>暂无%s数据</strong></p>"
            "<p>开始用小狼毫打字后自动记录；按天/按分钟聚合来自 "
            "<code>input_count_raw.txt</code>。</p></div></div>" % scale_label
        )
    avgctl = ""
    if avg_chk_id:
        avgctl = (
            '<label class="chk"><input type="checkbox" id="%s"> '
            "显示去零平均线（字=蓝色虚线、键=橙色虚线，字、键各自剔除 0 值后求平均）"
            "</label>" % avg_chk_id
        )
    note = (
        '<div class="note">%s 共 %d 个数据点%s</div>'
        % (scale_label, len(points), ("；" + extra_note) if extra_note else "")
    )
    return '<div class="pane pane-%s">%s%s%s</div>' % (scale_name, body, avgctl, note)


def build_html(data, generated_at, summary_path, raw_path, demo=False):
    parts = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="zh-CN">')
    parts.append("<head>")
    parts.append('<meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    parts.append("<title>小狼毫 · 输入统计</title>")
    parts.append("<style>%s</style>" % CSS)
    parts.append("</head>")
    parts.append('<body><div class="wrap">')
    parts.append("<h1>小狼毫 · 输入统计折线图（每日 / 按天聚合 / 按分钟聚合）</h1>")
    if demo:
        parts.append(
            '<div class="banner">演示图：为合成的示例数据（非真实统计）。'
            "真实图表见 <code>input_count_chart.html</code>。</div>"
        )
    parts.append(
        '<div class="sub">数据源：<code>%s</code>（每日汇总）+ <code>%s</code>（采样间隔为1分钟的数据）'
        " — 由 Rime-input-count 插件自动记录。悬停数据点看具体数值。</div>"
        % (html.escape(os.path.basename(summary_path)), html.escape(os.path.basename(raw_path)))
    )

    days_map = data["days"]                       # 日汇总（权威，= ii 弹窗数字）
    minutes = data["minutes"]
    raw_days = aggregate(minutes, 8)

    # 每日以汇总为准（保证与 ii 弹窗一致）；分钟级只在汇总缺失时补位
    day_map = dict(raw_days)
    day_map.update(days_map)

    # 图表：把缺口补 0 成连续时间轴（仅渲染，不写回数据文件），横轴照常显示没打字的时段
    day_points = continuous(day_map, "day", MAX_POINTS["day"])
    dayagg_points = continuous(raw_days, "day", MAX_POINTS["day"])
    minute_points = continuous(minutes, "minute", MAX_POINTS["minute"])
    # 卡片/汇总仍用「有数据」的观测值，避免被补 0 的空档拉低
    day_obs = [(k, day_map[k][0], day_map[k][1]) for k in sorted(day_map)]

    cards = []
    today = datetime.date.today().strftime("%Y%m%d")
    if today in day_map:
        cards.append(
            card(
                "今日",
                "%s <small>字 / %s 键</small>"
                % (fmt(day_map[today][0]), fmt(day_map[today][1])),
            )
        )
    else:
        cards.append(card("今日", "<small>尚未记录</small>"))
    cards.append(card("记录天数", fmt(len(day_map)), "天"))
    cards.append(card("累计上屏", fmt(data["total_words"]), "字"))
    cards.append(card("累计按键", fmt(data["total_keys"]), "键"))
    if day_obs:
        avg_w = sum(p[1] for p in day_obs) / float(len(day_obs))
        avg_k = sum(p[2] for p in day_obs) / float(len(day_obs))
        cards.append(card("日均上屏", fmt(avg_w), "字"))
        cards.append(card("日均按键", fmt(avg_k), "键"))
    else:
        cards.append(card("日均上屏", "<small>—</small>"))
        cards.append(card("日均按键", "<small>—</small>"))
    cards.append(card("分钟级记录", fmt(len(minutes)), "条"))
    parts.append('<div class="cards">%s</div>' % "".join(cards))

    parts.append('<div class="tabs">')
    parts.append('<input type="radio" name="scale" id="s-day" checked>')
    parts.append('<input type="radio" name="scale" id="s-dagg">')
    parts.append('<input type="radio" name="scale" id="s-min">')
    parts.append('<div class="tabbar">')
    parts.append('<label for="s-day">每日</label>')
    parts.append('<label for="s-dagg">按天聚合</label>')
    parts.append('<label for="s-min">按分钟聚合</label>')
    parts.append("</div>")
    parts.append(pane_html("day", "每日", day_points, lab_day, time_day,
                           "ii 弹窗亦可查看", avg=True, avg_chk_id="dayAvgChk"))

    # 按天聚合面板：可滚动 + 组距可输入（JS 渲染；无 JS 时按 1 天静态 SVG 兜底）
    min_raw = json.dumps(
        [[key, w, kk] for key, (w, kk) in sorted(minutes.items())], separators=(",", ":")
    )
    dagbody = []
    dagbody.append('<div class="minctl">')
    dagbody.append('<span class="minctl-label">组距（每点覆盖天数，1–365）：</span>')
    dagbody.append(
        '<input id="dInput" class="bm-input" type="number" min="1" max="365" step="1" '
        'value="1" list="dOpts" placeholder="1-365">'
    )
    dagbody.append('<datalist id="dOpts">')
    for opt, olab in ((1, "1 天"), (2, "2 天"), (3, "3 天"), (7, "7 天（一周）"),
                      (14, "14 天"), (30, "30 天（约一个月）"), (90, "90 天（约一季）"),
                      (180, "180 天（半年）"), (365, "365 天（一年）")):
        dagbody.append('<option value="%d">%s</option>' % (opt, olab))
    dagbody.append("</datalist>")
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
    dagbody.append(
        '<label class="chk"><input type="checkbox" id="dAvgChk"> '
        "显示去零平均线（字=蓝色虚线、键=橙色虚线，字、键各自剔除 0 值后求平均）</label>"
    )
    dagbody.append(
        '<div class="scroll-hint">默认每点 1 天并定位至最近的数据；向左滚动查看更早的数据。'
        "左右两侧纵轴刻度始终固定显示（左轴=字、右轴=键）；横轴标出每点的起始日期，"
        "悬停数据点看该组覆盖的日期范围与数值。</div>"
    )
    dagbody.append(
        '<div class="note">由 <code>input_count_raw.txt</code> 按天聚合；在上方下拉框选 '
        "1/2/3/7/14/30/90/180/365，或直接输入 1–365 的任意天数后回车/点「绘图」。</div>"
    )
    parts.append('<div class="pane pane-dagg">%s</div>' % "".join(dagbody))

    # 按分钟聚合面板：可滚动 + 组距可输入（JS 渲染；无 JS 时显示静态 SVG 兜底）
    mbody = []
    mbody.append('<div class="minctl">')
    mbody.append('<span class="minctl-label">组距（每点覆盖分钟数，1–1440）：</span>')
    mbody.append(
        '<input id="bmInput" class="bm-input" type="number" min="1" max="1440" step="1" '
        'value="1" list="bmOpts" placeholder="1-1440">'
    )
    mbody.append('<datalist id="bmOpts">')
    for opt, olab in ((1, "1 分钟"), (5, "5 分钟"), (10, "10 分钟"),
                      (15, "15 分钟"), (30, "30 分钟"), (60, "60 分钟（1 小时）"),
                      (120, "120 分钟（2 小时）"), (360, "360 分钟（6 小时）"),
                      (720, "720 分钟（12 小时）"), (1440, "1440 分钟（1 天）")):
        mbody.append('<option value="%d">%s</option>' % (opt, olab))
    mbody.append("</datalist>")
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
    mbody.append(
        '<label class="chk"><input type="checkbox" id="mAvgChk"> '
        "显示去零平均线（字=蓝色虚线、键=橙色虚线，字、键各自剔除 0 值后求平均）</label>"
    )
    mbody.append(
        '<label class="chk"><input type="checkbox" id="minDropZero"> '
        "删去0值（勾选后分钟级图表不绘制 0 值点，只把不为 0 的数据按时间顺序绘制出来；"
        "横轴时刻刻度与日期标注随之只标剩余的数据点）</label>"
    )
    mbody.append(
        '<div class="scroll-hint">默认按 1 分钟绘图并定位至最近的数据；向左滚动查看更早的数据。'
        "日期标注在每天 0:00 数据点的正下方（覆盖该点以右当天的数据）；"
        "滚动到看不到 0:00 时，当前日期固定显示在左下角（左侧纵轴下方）。</div>"
    )
    mbody.append(
        '<div class="note">由 <code>input_count_raw.txt</code> '
        "聚合；在上方下拉框选 1/5/10/15/30/60/120/360/720/1440，"
        "或直接输入 1–1440 的任意分钟数后回车/点「绘图」。</div>"
    )
    parts.append('<div class="pane pane-min">%s</div>' % "".join(mbody))
    parts.append("</div>")

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
    foot.append("分钟级原始文件：%s" % html.escape(raw_path))
    foot.append(
        "1分钟采样间隔的数据在早期有部分缺失，造成不同粒度的数据时间范围略有不一致。已考虑修复"
    )
    foot.append(
        "刷新方式：双击 <code>查看每日统计.bat</code>，或重新运行 "
        "<code>python plot_input_count.py</code>。"
    )
    parts.append('<div class="foot">%s</div>' % "<br>".join(foot))
    parts.append('<div id="tt" class="tooltip"></div>')
    parts.append("<script>window.MIN_RAW=%s;</script>" % min_raw)
    parts.append("<script>%s</script>" % CHART_JS)
    parts.append("</div></body></html>")
    return "\n".join(parts)


def synthesize_demo():
    rnd = random.Random(42)
    now = datetime.datetime.now().replace(second=0, microsecond=0)
    minutes = {}
    for day_back in range(21):
        base = (now - datetime.timedelta(days=day_back)).replace(hour=0, minute=0)
        for hour in range(7, 23):
            density = 0.62 if 9 <= hour <= 21 else 0.30
            if rnd.random() > density:
                continue
            for minute in range(60):
                if rnd.random() > 0.55:
                    continue
                dt = base + datetime.timedelta(hours=hour, minutes=minute)
                if dt > now:
                    continue
                w = rnd.randint(3, 46)
                k = w * rnd.randint(2, 4) + rnd.randint(0, 14)
                minutes[dt.strftime("%Y%m%d%H%M")] = (w, k)
    total_w = sum(v[0] for v in minutes.values())
    total_k = sum(v[1] for v in minutes.values())
    day_map = aggregate(minutes, 8)
    return {
        "start_iso": (now - datetime.timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S"),
        "total_words": total_w,
        "total_keys": total_k,
        "minutes": minutes,
        "days": day_map,
    }


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
    ap.add_argument("--demo", action="store_true", help="synthesize sample data and label as demo")
    ap.add_argument("--png", action="store_true",
                    help="also save PNG if matplotlib is installed (optional, day scale)")
    args = ap.parse_args(argv)

    if args.demo:
        data = synthesize_demo()
        summary_path, raw_path = "(synthesized)", "(synthesized)"
    else:
        summary = parse_summary(args.input)
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
    doc = build_html(data, now, summary_path, raw_path, demo=args.demo)

    try:
        out_dir = os.path.dirname(os.path.abspath(args.output))
        if out_dir and not os.path.isdir(out_dir):
            os.makedirs(out_dir)
        with open(args.output, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(doc)
    except OSError as exc:
        print("ERROR: cannot write %s: %s" % (args.output, exc))
        return 1

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
