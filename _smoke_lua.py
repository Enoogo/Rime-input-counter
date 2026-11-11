#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_smoke_lua.py - lua/keylog.lua 的回归测试（在真实 rime.dll 的 Lua 里跑）。

不碰真实数据：把 keylog.lua 的 data_dir 重定向到临时目录，再用 rime.dll 导出的
Lua C API（luaL_newstate / luaL_loadbufferx / lua_pcallk）执行，并注入一段测试驱动，
验证：
  1. 按键 -> keylog\ 记 token、keylog_ts\ 记时间戳，一一对应（抬起的键两边都不记）；
  2. 时间戳格式 HHMMSSmmm（9 字节）、单调、每事件 10 字节（含 LF）；
  3. 毫秒相位校准准确（秒进位后立刻打一键，毫秒位应接近 0）；
  4. settings.yaml 的 keylog_timestamp 开关（false 停写、true 恢复、缺省开启）；
  5. clock() 墙钟语义懒校验在本机判定为「墙钟」。

用法：python _smoke_lua.py
"""
import ctypes
import os
import re
import shutil
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KEYLOG_LUA = os.path.join(os.path.dirname(BASE_DIR), "lua", "keylog.lua")
RIME_DLL = r"C:\Program Files\Rime\weasel-0.17.4\rime.dll"

DRIVER = r'''
-- ===== 测试驱动（由 _smoke_lua.py 注入，不属于部署代码） =====
local function key_stub(repr, rel)
  return {
    release = function(self) return rel == true end,
    repr = function(self) return repr end,
  }
end
local function read_lines(path)
  local t = {}
  local f = io.open(path, "r")
  if f then
    for line in f:lines() do t[#t + 1] = line end
    f:close()
  end
  return t
end
local function write_file(path, text)
  local f = assert(io.open(path, "w"))
  f:write(text)
  f:close()
end
local res = {}
local today = os.date("%Y%m%d")
local tspath = ts_dir .. "\\" .. today .. ".txt"
local klpath = keylog_dir .. "\\" .. today .. ".txt"

-- 1) 三个按键 + 一次抬起：keylog 记 3 个 token、keylog_ts 记 3 行
M.processor(key_stub("a"), nil)
M.processor(key_stub("BackSpace"), nil)
M.processor(key_stub("0x0000"), nil)
M.processor(key_stub("x", true), nil)
local kl = read_lines(klpath)
local ts = read_lines(tspath)
res[#res + 1] = "ts_count_3=" .. tostring(#ts == 3)
-- 行首 HHMM 去掉后应恰好是 a BACK UNK（跨分钟分行也不受影响）
res[#res + 1] = "kl_token_ok=" .. tostring(table.concat(kl, ""):gsub("%d%d%d%d", ""):find("aBACKUNK", 1, true) ~= nil)

-- 2) 格式 HHMMSSmmm + 单调
local ok_fmt, mono, prev = true, true, -1
for _, ln in ipairs(ts) do
  if not ln:match("^%d%d%d%d%d%d%d%d%d$") then ok_fmt = false end
  local v = tonumber(ln)
  if prev >= 0 and v < prev then mono = false end
  prev = v
end
res[#res + 1] = "ts_format=" .. tostring(ok_fmt)
res[#res + 1] = "ts_monotonic=" .. tostring(mono)

-- 3) 毫秒相位校准：等秒进位后立刻打一键 -> 该行毫秒位应接近 0，秒位应=进位后的秒
local prev_t = os.time()
while os.time() == prev_t do end
local flip_hms = os.date("%H%M%S")
M.processor(key_stub("z"), nil)
local ts2 = read_lines(tspath)
local last = ts2[#ts2]
res[#res + 1] = "phase_sec_ok=" .. tostring(last:sub(1, 6) == flip_hms)
res[#res + 1] = "phase_ms=" .. last:sub(7, 9)

-- 4) settings.yaml 开关：false 停写时间戳（keylog 照常）、true 恢复、缺省开启
ts_cfg.t = nil
write_file(ts_cfg_path, "# test config\nkeylog_timestamp: false\n")
res[#res + 1] = "switch_off=" .. tostring(ts_enabled() == false)
local n_before = #read_lines(tspath)
M.processor(key_stub("q"), nil)
res[#res + 1] = "off_no_ts=" .. tostring(#read_lines(tspath) == n_before)
res[#res + 1] = "off_keylog_ok=" .. tostring(table.concat(read_lines(klpath), ""):find("q", 1, true) ~= nil)
ts_cfg.t = nil
write_file(ts_cfg_path, "keylog_timestamp: true\n")
res[#res + 1] = "switch_on=" .. tostring(ts_enabled() == true)
M.processor(key_stub("w"), nil)
res[#res + 1] = "on_writes_ts=" .. tostring(#read_lines(tspath) == n_before + 1)
os.remove(ts_cfg_path)
ts_cfg.t = nil
res[#res + 1] = "default_on=" .. tostring(ts_enabled() == true)

-- 5) 墙钟语义懒校验：观察窗口 >= 3 秒后应判定 wall=true（本机 os.clock 是墙钟）
local p = os.clock()
while os.clock() - p < 3.2 do end
M.processor(key_stub("e"), nil)
res[#res + 1] = "wall_verdict=" .. tostring(ts_clk.wall)

return table.concat(res, "\n")
'''


def run_lua(src):
    lua = ctypes.WinDLL(RIME_DLL)
    lua.luaL_newstate.restype = ctypes.c_void_p
    lua.luaL_openlibs.argtypes = [ctypes.c_void_p]
    lua.luaL_loadbufferx.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                     ctypes.c_size_t, ctypes.c_char_p, ctypes.c_char_p]
    lua.luaL_loadbufferx.restype = ctypes.c_int
    lua.lua_pcallk.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
    lua.lua_pcallk.restype = ctypes.c_int
    lua.lua_tolstring.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                  ctypes.POINTER(ctypes.c_size_t)]
    lua.lua_tolstring.restype = ctypes.c_char_p
    lua.lua_close.argtypes = [ctypes.c_void_p]

    state = lua.luaL_newstate()
    if not state:
        raise RuntimeError("luaL_newstate failed")
    try:
        lua.luaL_openlibs(state)
        buf = src.encode("utf-8")
        rc = lua.luaL_loadbufferx(state, buf, len(buf), b"keylog_test", None)
        if rc != 0:
            raise SyntaxError(lua.lua_tolstring(state, -1, None).decode("utf-8", "replace"))
        rc = lua.lua_pcallk(state, 0, 1, 0, None, None)
        if rc != 0:
            raise RuntimeError(lua.lua_tolstring(state, -1, None).decode("utf-8", "replace"))
        out = lua.lua_tolstring(state, -1, None)
        return out.decode("utf-8", "replace") if out else ""
    finally:
        lua.lua_close(state)


def main():
    with open(KEYLOG_LUA, "r", encoding="utf-8") as fh:
        src = fh.read()
    if "return M" not in src:
        print("FAIL  keylog.lua 里找不到 return M")
        return 1

    tmp = tempfile.mkdtemp(prefix="keylog_test_")
    try:
        lua_dir = tmp.replace("\\", "\\\\")           # Lua 字符串里的反斜杠要转义
        src = src.replace(
            'local data_dir = "D:\\\\MiniPrograms\\\\RimeData\\\\Rime-input-count"',
            'local data_dir = "%s"' % lua_dir, 1)
        head, _sep, tail = src.rpartition("return M")
        # DRIVER 末尾自带 return，直接顶替原来的 return M
        src = head + DRIVER + tail

        try:
            out = run_lua(src)
        except SyntaxError as exc:
            print("FAIL  Lua 语法错误: %s" % exc)
            return 1

        got = {}
        for line in out.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                got[k] = v

        def check(name, cond):
            print(("PASS  " if cond else "FAIL  ") + name)
            return cond

        ok = True
        for key in ("ts_count_3", "kl_token_ok", "ts_format", "ts_monotonic",
                    "phase_sec_ok", "switch_off", "off_no_ts", "off_keylog_ok",
                    "switch_on", "on_writes_ts", "default_on", "wall_verdict"):
            ok &= check("%s = %s" % (key, got.get(key)), got.get(key) == "true")

        ms = int(got.get("phase_ms", "999"))
        ok &= check("phase_ms = %s（秒进位后立即按键，应 < 100）" % got.get("phase_ms"), ms < 100)

        # 每事件 10 字节（9 字节时间戳 + 1 字节 LF）
        today = __import__("datetime").date.today().strftime("%Y%m%d")
        ts_path = os.path.join(tmp, "keylog_ts", today + ".txt")
        with open(ts_path, "rb") as fh:
            data = fh.read()
        n = data.count(b"\n")
        ok &= check("每事件 10 字节（%d 行 %d 字节）" % (n, len(data)),
                    n > 0 and len(data) == 10 * n)
        ok &= check("行尾是 LF（无 CR）", b"\r" not in data)

        # keylog\ 与 keylog_ts\ 键数一一对应（keylog 共 a BACK UNK z q w e = 7 个键）
        kl_path = os.path.join(tmp, "keylog", today + ".txt")
        with open(kl_path, "r", encoding="utf-8") as fh:
            kl_text = fh.read()
        kall = re.sub(r"\s", "", re.sub(r"^\d{4}", "", kl_text, flags=re.M))
        ok &= check("keylog 记录 7 个键、时间戳 6 行（关期间的 q 不记时间戳）",
                    kall == "aBACKUNKzqwe" and n == 6)
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
