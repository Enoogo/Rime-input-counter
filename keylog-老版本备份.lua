-- 按键明细记录器（keylog）旧格式备份：2026-10-19 改为新记录形式前的原始版本。
-- 新版本部署在 D:\MiniPrograms\RimeData\lua\keylog.lua。
-- 旧记录（keylog\ 里改格式之前写的 txt）不需要也不应该被改写。
local M = {}

-- ===== 安装配置 =====
-- 按键明细目录：统计工具同目录下的 keylog\（首次写入时自动创建）
local data_dir = "D:\\MiniPrograms\\RimeData\\Rime-input-count"
local keylog_dir = data_dir .. "\\keylog"

-- ===== 键名 -> 记录标记 =====
-- key:repr() 对字母/数字/部分标点直接返回字符本身（原样记录，无需列在这里）；
-- 这里列出的是「空格与标点」的 X 键名、「功能键」的简称、组合键里的修饰键简称。
local key_map = {
  -- 可打印字符（X keysym 名 -> 实际字符）
  space = " ", exclam = "!", at = "@", numbersign = "#", dollar = "$", percent = "%",
  ampersand = "&", asterisk = "*", parenleft = "(", parenright = ")", minus = "-",
  underscore = "_", equal = "=", plus = "+", bracketleft = "[", bracketright = "]",
  braceleft = "{", braceright = "}", backslash = "\\", bar = "|", semicolon = ";",
  colon = ":", apostrophe = "'", quotedbl = "\"", grave = "`", asciitilde = "~",
  comma = ",", less = "<", period = ".", greater = ">", slash = "/", question = "?",
  -- 功能键简称
  BackSpace = "BS", Return = "CR", Escape = "ESC", Tab = "TAB", ISO_Left_Tab = "TAB",
  Shift = "SH", Shift_L = "SH", Shift_R = "SH",
  Control = "CT", Control_L = "CT", Control_R = "CT",
  Alt = "AL", Alt_L = "AL", Alt_R = "AL", Mod1 = "AL",
  Super = "WN", Super_L = "WN", Super_R = "WN",
  Meta = "WN", Meta_L = "WN", Meta_R = "WN",
  Hyper = "WN", Hyper_L = "WN", Hyper_R = "WN",
  Up = "↑", Down = "↓", Left = "←", Right = "→",
  Home = "HM", End = "ED", Page_Up = "PU", Page_Down = "PD",
  Delete = "DL", Insert = "IS", Caps_Lock = "CAPS", Num_Lock = "NUM",
  Print = "PRT", Scroll_Lock = "SCL", Pause = "PAU", Menu = "MNU",
  KP_Enter = "CR", KP_Tab = "TAB", KP_Delete = "DL", KP_Home = "HM", KP_End = "ED",
  KP_Page_Up = "PU", KP_Page_Down = "PD", KP_Up = "↑", KP_Down = "↓",
  KP_Left = "←", KP_Right = "→", KP_Insert = "IS",
}

-- key:repr() 形如 "a"、"Shift+a"、"space"、"BackSpace" -> 记录用的短标记
local function token_for(repr)
  local parts = {}
  for p in repr:gmatch("[^+]+") do
    parts[#parts + 1] = p
  end
  if #parts == 0 then
    return ""
  end
  local base = parts[#parts]
  if #parts == 1 then
    return key_map[base] or base
  end
  -- Shift + 字母 = 直接写那个大写字母
  if #parts == 2 and parts[1] == "Shift" and #base == 1 and base:match("%a") then
    return base:upper()
  end
  local mods = {}
  for i = 1, #parts - 1 do
    mods[#mods + 1] = key_map[parts[i]] or parts[i]
  end
  return table.concat(mods, "+") .. "+" .. (key_map[base] or base)
end

-- ===== 写文件：每分钟一行（行首 HHMM），只写有按键的分钟 =====
local kl = { day = nil, min = nil }   -- 当前打开的行属于哪一天、哪一分钟（min=nil 表示该文件还没开行）

local dir_made = false
local function kl_open_append(path)
  local f = io.open(path, "a")
  if f then
    return f
  end
  if not dir_made then
    dir_made = true
    pcall(function()
      os.execute('mkdir "' .. keylog_dir .. '" >nul 2>nul')
    end)
    f = io.open(path, "a")
  end
  return f
end

-- 进程重启后从文件末行恢复「当前打开行」，同一分钟的键才续写同一行
local function kl_recover(day)
  kl.day, kl.min = day, nil
  local f = io.open(keylog_dir .. "\\" .. day .. ".txt", "r")
  if not f then
    return
  end
  local last = ""
  for line in f:lines() do
    if line ~= "" then
      last = line
    end
  end
  f:close()
  if last:match("^%d%d%d%d") then
    kl.min = tonumber(last:sub(1, 2)) * 60 + tonumber(last:sub(3, 4))
  end
end

local function kl_add(token)
  local day = os.date("%Y%m%d")
  local hhmm = os.date("%H%M")
  if kl.day ~= day then
    kl_recover(day)
  end
  local minute = tonumber(hhmm:sub(1, 2)) * 60 + tonumber(hhmm:sub(3, 4))
  local sep
  if kl.min == minute then
    sep = ""                    -- 续写当前这一行
  elseif kl.min == nil then
    sep = hhmm                  -- 今天第一行：行首 HHMM
  else
    sep = "\n" .. hhmm          -- 换了分钟：换行 + 新行首 HHMM
  end
  local f = kl_open_append(keylog_dir .. "\\" .. day .. ".txt")
  if f then
    f:write(sep, token)
    f:close()
  end
  kl.min = minute
end

-- ===== 处理器入口：记完键原样放行（kNoop），绝不影响输入 =====
function M.processor(key, env)
  pcall(function()
    if not key then
      return
    end
    local ok_rel, is_rel = pcall(function()
      return key:release()
    end)
    if ok_rel and is_rel then
      return    -- 只记按下，不记抬起
    end
    local repr = key:repr()
    if not repr or repr == "" then
      return
    end
    kl_add(token_for(repr))
  end)
  return 2
end

-- librime-lua 的模块式绑定（lua_processor@*keylog）对任何组件都统一取模块的 func 字段，
-- 所以把处理器函数同时挂到 func 上（processor 名字保留，兼容旧式写法 lua_processor@keylog）。
M.func = M.processor

return M
