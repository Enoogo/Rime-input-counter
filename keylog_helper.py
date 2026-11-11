#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""keylog_helper.py - 按键明细本地小服务（图表页的后端）。

图表 HTML 本身不能读文件/建副本/开程序，所以「点按显示按键」「双击开副本」两个功能
由这个小服务执行：只监听 127.0.0.1，由 查看每日统计.bat（或图表生成器）自动后台启动。

接口（均支持 JSONP 回调参数 cb，方便 file:// 页面跨源调用）：
    GET /ping                       心跳
    GET /keys?d1=YYYYMMDD&d2=YYYYMMDD&m1=<分钟>&m2=<分钟>
        提取 keylog\\<day>.txt 中行首 HHMM 落在 [m1,m2] 的行，按天返回原文
    GET /open?d1=...&d2=...&m1=...&m2=...
        找到区间内第一行按键 -> 复制该日 txt、删掉该行之前的内容 -> 清空旧副本
        -> 系统默认程序打开新副本（副本第一行即对应行，等于自动跳到那一行）

按键明细文件格式（keylog\\20260101.txt，每天一个，由 lua/keylog.lua 写入）：
    每个「有按键的分钟」恰好一行：行首 4 位 HHMM + 该分钟依次按下的键（键之间无分隔符）。
    无按键的分钟不写行。
"""

import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KEYLOG_DIR = os.path.join(BASE_DIR, "keylog")
COPIES_DIR = os.path.join(BASE_DIR, "keylog_copies")

PORT = 47321
IDLE_EXIT_SECONDS = 8 * 3600   # 8 小时无请求自动退出，避免留下常驻进程
MAX_DAYS = 400                  # d1..d2 跨度上限（防异常参数扫盘）

CB_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
DAY_RE = re.compile(r"^\d{8}$")


# ---------- 按键明细文件解析 ----------

def day_lines(day):
    """读一天的按键明细，返回原始行列表（不含换行符，行尾可能带 \\r）。文件不存在返回 []。"""
    path = os.path.join(KEYLOG_DIR, day + ".txt")
    if not os.path.isfile(path):
        return []
    try:
        # newline="" 关闭换行翻译，保证副本与原文件逐字节一致
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
            return fh.read().split("\n")
    except OSError:
        return []


def line_minute(line):
    """行首 4 位 HHMM -> 当天第几分钟；不是合法按键行返回 None。"""
    if len(line) < 4 or not line[:4].isdigit():
        return None
    hh, mm = int(line[0:2]), int(line[2:4])
    if hh > 23 or mm > 59:
        return None
    return hh * 60 + mm


def iter_days(d1, d2):
    try:
        a = datetime.strptime(d1, "%Y%m%d")
        b = datetime.strptime(d2, "%Y%m%d")
    except ValueError:
        return []
    if b < a:
        a, b = b, a
    if (b - a).days >= MAX_DAYS:
        b = a + timedelta(days=MAX_DAYS - 1)
    out = []
    cur = a
    while cur <= b:
        out.append(cur.strftime("%Y%m%d"))
        cur += timedelta(days=1)
    return out


def extract_keys(d1, d2, m1, m2):
    """区间内按键原文：[{day, text, lines}]，只含有按键行的天（显示用，去掉行尾 \\r）。"""
    got = []
    for day in iter_days(d1, d2):
        rows = [ln.rstrip("\r") for ln in day_lines(day)
                if (m := line_minute(ln)) is not None and m1 <= m <= m2]
        if rows:
            got.append({"day": day, "text": "\n".join(rows), "lines": len(rows)})
    return got


def find_first_line(d1, d2, m1, m2):
    """区间内第一条按键行 -> (day, hhmm, 行下标, 当天全部行)；没有则 None。"""
    for day in iter_days(d1, d2):
        rows = day_lines(day)
        for idx, ln in enumerate(rows):
            m = line_minute(ln)
            if m is not None and m1 <= m <= m2:
                return day, ln[:4], idx, rows
    return None


def make_copy(day, hhmm, idx, rows):
    """生成副本：删掉对应行之前的所有内容；顺带清空以前创建的所有副本。"""
    os.makedirs(COPIES_DIR, exist_ok=True)
    for name in os.listdir(COPIES_DIR):
        p = os.path.join(COPIES_DIR, name)
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass
    copy_path = os.path.join(COPIES_DIR, "%s-%s副本.txt" % (day, hhmm))
    with open(copy_path, "w", encoding="utf-8", newline="") as fh:
        fh.write("\n".join(rows[idx:]))
    return copy_path


# ---------- HTTP 服务 ----------

_last_activity = time.time()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")

    def _reply(self, payload, cb=None):
        body = json.dumps(payload, ensure_ascii=False)
        if cb and CB_RE.match(cb):
            data = ("%s(%s);" % (cb, body)).encode("utf-8")
            ctype = "text/javascript; charset=utf-8"
        else:
            data = body.encode("utf-8")
            ctype = "application/json; charset=utf-8"
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        global _last_activity
        _last_activity = time.time()
        try:
            self._route()
        except Exception as exc:  # 服务绝不能把异常抛给打字统计的用户
            self._reply({"ok": False, "reason": str(exc)})

    def _route(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        cb = (q.get("cb") or [None])[0]

        if url.path == "/ping":
            self._reply({"ok": True, "port": PORT}, cb)
            return

        def num(name, default):
            try:
                return int((q.get(name) or [str(default)])[0])
            except ValueError:
                return default

        d1 = (q.get("d1") or [""])[0]
        d2 = (q.get("d2") or [d1])[0]
        if not DAY_RE.match(d1):
            self._reply({"ok": False, "reason": "bad day"}, cb)
            return
        if not DAY_RE.match(d2):
            d2 = d1
        m1 = max(0, min(1439, num("m1", 0)))
        m2 = max(0, min(1439, num("m2", 1439)))
        if m2 < m1:
            m1, m2 = m2, m1

        if url.path == "/keys":
            days = extract_keys(d1, d2, m1, m2)
            self._reply({"ok": True, "days": days,
                         "total": sum(d["lines"] for d in days)}, cb)
            return

        if url.path == "/open":
            hit = find_first_line(d1, d2, m1, m2)
            if not hit:
                self._reply({"ok": False, "reason": "no_keys"}, cb)
                return
            day, hhmm, idx, rows = hit
            copy_path = make_copy(day, hhmm, idx, rows)
            os.startfile(copy_path)   # 系统默认程序打开；副本首行=对应行
            self._reply({"ok": True, "copy": copy_path, "day": day,
                         "hhmm": hhmm}, cb)
            return

        self._reply({"ok": False, "reason": "unknown api"}, cb)


class QuietServer(ThreadingHTTPServer):
    """客户端提前断开（keep-alive 超时等）不打印堆栈，保持后台安静。"""

    def handle_error(self, request, client_address):
        pass


def _idle_watchdog(srv):
    while True:
        time.sleep(60)
        if time.time() - _last_activity > IDLE_EXIT_SECONDS:
            try:
                srv.shutdown()
            except Exception:
                pass
            return


def main():
    try:
        srv = QuietServer(("127.0.0.1", PORT), Handler)
    except OSError:
        return 0  # 已有实例在跑（或端口被占）：静默退出，功能照常
    threading.Thread(target=_idle_watchdog, args=(srv,), daemon=True).start()
    try:
        srv.serve_forever(poll_interval=30)
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
