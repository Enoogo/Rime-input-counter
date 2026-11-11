-- 输入统计：上屏字数 + 按键数统计（含分钟级原始数据）
-- 来源：ramonmi / Rime-input-count（gist: b1ac25bbe017c375b17fe23f0158d878）
-- 本地化修改（本机安装版）：
--   1) db_path / raw_path 改为本机绝对路径
--   2) command_key 由 "sS" 改为 "ii"
--      原因：朙月拼音（luna_pinyin_simp）的 speller/alphabet 只含小写字母，
--      "S" 无法进入输入码，"sS" 永远触发不了；"ii" 不是合法拼音，日常不会误触。
--   3) 退格分支不再把 last_code 清空，改为跟踪当前输入码
--      （原逻辑每次退格会把剩余编码长度虚计入按键数；此处做了一处小改进）
--   4) 新增分钟级原始数据 input_count_raw.txt（append），行格式：
--        e=YYYYMMDDHHMM w=<上屏字数> k=<按键数>
--      同一分钟可有多行，读取时按需聚合成 分钟/小时/日 三档，供图表切换时间尺度。
local M = {}

-- 存储路径（根据操作系统修改路径，当前为 Windows 绝对路径）
local db_path = "D:\\MiniPrograms\\RimeData\\input_count.txt"
local raw_path = "D:\\MiniPrograms\\RimeData\\input_count_raw.txt"
local raw_path_tmp = "D:\\MiniPrograms\\RimeData\\input_count_raw.tmp"

-- 输入统计触发按键（中文状态下依次输入 ii，统计结果显示在候选框，Esc 关闭）
local command_key = "ii"

local save_stat

local function format_count(n)
  local num = tonumber(n) or 0
  local function trunc(v, digits)
    local p = 10 ^ digits
    return math.floor(v * p) / p
  end
  if num < 1000 then
    return string.format("%d", math.floor(num))
  elseif num < 10000 then
    return string.format("%.2f千", trunc(num / 1000, 2))
  else
    return string.format("%.2f万", trunc(num / 10000, 2))
  end
end

-- ===== 分钟级数据：临时文件累计 + 跨分钟聚合成一行 =====
-- input_count_raw.txt   最终数据（每分钟恰好一行，append-only，写入开销恒定）
-- input_count_raw.tmp   当前这一分钟的流水（逐条追加），跨分钟后聚合成一行写入上面并清空
-- 这样最终文件里每个时间戳只出现一次，且数据量大时写入也不会变慢。

-- 把 tmp 里上一分钟的流水聚合成一行，追加到 raw，然后清空 tmp
local function raw_finalize_tmp(minute_fallback)
  local sumw, sumk, minute = 0, 0, nil
  local f = io.open(raw_path_tmp, "r")
  if f then
    for line in f:lines() do
      local m, w, k = line:match("^e=(%d+)%s+w=(-?%d+)%s+k=(-?%d+)$")
      if m then
        if not minute then
          minute = m
        end
        sumw = sumw + (tonumber(w) or 0)
        sumk = sumk + (tonumber(k) or 0)
      end
    end
    f:close()
  end
  -- 清空 tmp（覆盖为空）
  local t = io.open(raw_path_tmp, "w")
  if t then
    t:close()
  end
  local target = minute or minute_fallback
  if target and (sumw > 0 or sumk > 0) then
    local r = io.open(raw_path, "a")
    if r then
      r:write(string.format("e=%s w=%d k=%d\n", target, sumw, sumk))
      r:close()
    end
  end
end

-- 记一次增量（字数/按键数）：先追加到 tmp 流水，跨分钟时把上一分钟聚合写入 raw
local function raw_add(s, dw, dk)
  s = s or _G.my_stat
  if not s then
    return
  end
  local slot = os.date("%Y%m%d%H%M")
  if s.raw_slot and s.raw_slot ~= slot then
    -- 跨分钟：把上一分钟的流水聚合成一行落到 raw，再开新的一分钟
    raw_finalize_tmp(s.raw_slot)
    s.raw_slot = slot
  end
  if not s.raw_slot then
    s.raw_slot = slot
  end
  local t = io.open(raw_path_tmp, "a")
  if t then
    t:write(string.format("e=%s w=%d k=%d\n", slot, tonumber(dw) or 0, tonumber(dk) or 0))
    t:close()
  end
end

-- 启动时恢复：tmp 里若有上次遗留的流水（进程重启/最后一分钟没跨过去）
local function raw_recover(s)
  s = s or _G.my_stat
  if not s then
    return
  end
  local f = io.open(raw_path_tmp, "r")
  if not f then
    s.raw_slot = os.date("%Y%m%d%H%M")
    return
  end
  local minute, sumw, sumk = nil, 0, 0
  for line in f:lines() do
    local m, w, k = line:match("^e=(%d+)%s+w=(-?%d+)%s+k=(-?%d+)$")
    if m then
      if not minute then
        minute = m
      end
      sumw = sumw + (tonumber(w) or 0)
      sumk = sumk + (tonumber(k) or 0)
    end
  end
  f:close()
  local now = os.date("%Y%m%d%H%M")
  if minute == now then
    -- 还是当前这一分钟：保留 tmp 继续累计，跨分钟时统一聚合
    s.raw_slot = now
  else
    -- 上一分钟（或更早）没写进 raw：现在补写一行，并清空 tmp
    if minute and (sumw > 0 or sumk > 0) then
      local r = io.open(raw_path, "a")
      if r then
        r:write(string.format("e=%s w=%d k=%d\n", minute, sumw, sumk))
        r:close()
      end
    end
    local t = io.open(raw_path_tmp, "w")
    if t then
      t:close()
    end
    s.raw_slot = now
  end
end

local function load_stat()
  if not _G.my_stat then
    _G.my_stat = {
      total_keys = 0,
      total_words = 0,
      day_keys = 0,
      day_words = 0,
      day = os.date("%Y%m%d"),
      last_code = "",
      start_iso = os.date("%Y-%m-%d %H:%M:%S"),
      history = {},
      -- 分钟级：当前分钟的流水写 input_count_raw.tmp，跨分钟聚合成一行写 input_count_raw.txt
      raw_slot = os.date("%Y%m%d%H%M")
    }
    raw_recover(_G.my_stat)
    local f = io.open(db_path, "r")
    if f then
      local history = {}
      for line in f:lines() do
        local day1, day_words1, day_keys1 = line:match("^day=(%d+)%s+day_words=(%d+)%s+day_keys=(%d+)$")
        if day1 then
          table.insert(history, {
            day = day1,
            day_words = tonumber(day_words1) or 0,
            day_keys = tonumber(day_keys1) or 0
          })
        else
          local total_words1, total_keys1 = line:match("^total_words=(%d+)%s+total_keys=(%d+)$")
          if total_words1 and total_keys1 then
            _G.my_stat.total_words = tonumber(total_words1) or _G.my_stat.total_words
            _G.my_stat.total_keys = tonumber(total_keys1) or _G.my_stat.total_keys
          else
            local k, v = line:match("([%w_]+)=(.+)")
            if k and v then
              if k == "day" then
                _G.my_stat.day = v
              elseif k == "start_iso" then
                _G.my_stat.start_iso = v
              elseif k == "last_code" then
                _G.my_stat.last_code = v
              elseif k == "total_words" then
                _G.my_stat.total_words = tonumber(v) or _G.my_stat.total_words
              elseif k == "total_keys" then
                _G.my_stat.total_keys = tonumber(v) or _G.my_stat.total_keys
              elseif k == "day_words" then
                _G.my_stat.day_words = tonumber(v) or _G.my_stat.day_words
              elseif k == "day_keys" then
                _G.my_stat.day_keys = tonumber(v) or _G.my_stat.day_keys
              else
                _G.my_stat[k] = tonumber(v) or 0
              end
            end
          end
        end
      end
      f:close()

      if #history > 0 then
        table.sort(history, function(a, b) return a.day < b.day end)
        local last = history[#history]
        _G.my_stat.day = last.day
        _G.my_stat.day_keys = last.day_keys
        _G.my_stat.day_words = last.day_words
        _G.my_stat.history = history
      else
        _G.my_stat.history = {}
      end
    end
  end

  -- 如果文件不存在，清空内存历史，避免删文件后旧记录残留
  do
    local f = io.open(db_path, "r")
    if f then
      f:close()
    else
      _G.my_stat.history = {}
    end
  end

  -- 按天重置今日统计
  local today = os.date("%Y%m%d")
  if _G.my_stat.day ~= today then
    local history = _G.my_stat.history or {}
    local prev_day = _G.my_stat.day
    local found = false
    for i = 1, #history do
      if history[i].day == prev_day then
        history[i].day_words = tonumber(_G.my_stat.day_words) or 0
        history[i].day_keys = tonumber(_G.my_stat.day_keys) or 0
        found = true
        break
      end
    end
    if not found and prev_day ~= nil and prev_day ~= "" then
      table.insert(history, {
        day = prev_day,
        day_words = tonumber(_G.my_stat.day_words) or 0,
        day_keys = tonumber(_G.my_stat.day_keys) or 0
      })
    end
    _G.my_stat.history = history

    _G.my_stat.day = today
    _G.my_stat.day_words = 0
    _G.my_stat.day_keys = 0
    _G.my_stat.last_code = ""
    save_stat()
  end

  return _G.my_stat
end

function save_stat()
  local f = io.open(db_path, "w")
  if f then
    -- 首行写入起始日期和时间（ISO 8601 格式）
    local start_iso = _G.my_stat.start_iso or os.date("%Y-%m-%d %H:%M:%S")
    _G.my_stat.start_iso = start_iso
    f:write("start_iso=" .. tostring(start_iso) .. "\n")

    -- 第二行写入累计统计
    f:write(string.format(
      "total_words=%d total_keys=%d\n",
      tonumber(_G.my_stat.total_words) or 0,
      tonumber(_G.my_stat.total_keys) or 0
    ))

    -- 按天一行输出统计项
    local history = _G.my_stat.history or {}
    local today = _G.my_stat.day
    local found = false
    for i = 1, #history do
      if history[i].day == today then
        history[i].day_words = tonumber(_G.my_stat.day_words) or 0
        history[i].day_keys = tonumber(_G.my_stat.day_keys) or 0
        found = true
        break
      end
    end
    if not found then
      table.insert(history, {
        day = today,
        day_words = tonumber(_G.my_stat.day_words) or 0,
        day_keys = tonumber(_G.my_stat.day_keys) or 0
      })
    end
    table.sort(history, function(a, b) return a.day < b.day end)
    _G.my_stat.history = history

    for i = 1, #history do
      local h = history[i]
      f:write(string.format(
        "day=%s day_words=%d day_keys=%d\n",
        h.day,
        h.day_words or 0,
        h.day_keys or 0
      ))
    end

    -- 其他字段保持兼容
    if _G.my_stat.last_code ~= nil then
      f:write("last_code=" .. tostring(_G.my_stat.last_code) .. "\n")
    end

    f:close()
  end
end

-- 核心：通过 Translator 逆向统计（新版 librime Lua 入口使用 func）
function M.func(input, seg, env)
  local s = load_stat()
  if input == "" then
    s.last_code = ""
    s.shrank = false
    return
  end
  if #input < #s.last_code then
    -- 退格：跟踪当前输入码，而不是清零（避免剩余编码被重复计数）
    -- 注意：标记必须持久化在状态表上（跨调用记忆），否则“触发->退格->再触发”
    -- 会把已经回退过的按键再回退一次，导致按键数越打越少
    s.last_code = input
    s.shrank = true
  end

  -- 统计逻辑：如果当前的输入码比上次长，说明按了键
  if input == command_key then
    if (not s.shrank) and s.last_code ~= input and s.last_code ~= "" and command_key:sub(1, #s.last_code) == s.last_code then
      local rollback = #s.last_code
      if rollback > 0 then
        s.total_keys = math.max(0, s.total_keys - rollback)
        s.day_keys = math.max(0, s.day_keys - rollback)
      end
    end
    s.last_code = input
    s.shrank = false
  elseif input ~= "" and input ~= s.last_code then
    if #input > #s.last_code then
      local diff = #input - #s.last_code
      s.total_keys = s.total_keys + diff
      s.day_keys = s.day_keys + diff
      raw_add(s, 0, diff) -- 分钟级按键增量（不含触发键回退，保持“按了就算”）
    end
    s.last_code = input
    s.shrank = false
  end

  -- 显示逻辑
  if input == command_key then
    save_stat()
    local day_words = format_count(s.day_words)
    local day_keys = format_count(s.day_keys)
    local total_words = format_count(s.total_words)
    local total_keys = format_count(s.total_keys)
    local from_date = (s.start_iso or ""):match("^(%d%d%d%d%-%d%d%-%d%d)") or ""
    local text = string.format("今日：%s字/%s键 | 总计：%s字/%s键", day_words, day_keys, total_words, total_keys)
    local comment = string.format("[%s—至今]", from_date)
    yield(Candidate("stat", seg.start, seg._end, text, comment))
  end
end

-- 捕捉上屏（利用 init 挂载监听，如果监听失效，至少按键数能动）
function M.init(env)
  load_stat()
  pcall(function()
    env.conn = env.engine.context.commit_notifier:connect(function(ctx)
      local text = ctx:get_commit_text()
      if text ~= "" and text ~= command_key then
        local _, count = text:gsub("[^\128-\193]", "")
        _G.my_stat.total_words = _G.my_stat.total_words + count
        _G.my_stat.day_words = _G.my_stat.day_words + count
        _G.my_stat.last_code = "" -- 上屏后重置编码追踪
        raw_add(_G.my_stat, count, 0) -- 分钟级字数增量
        save_stat()
      end
    end)
  end)
end

function M.processor(key, env)
  return 2 -- 彻底停用此组件的逻辑
end

return M
