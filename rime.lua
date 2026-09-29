-- rime.lua：librime-lua 脚本总入口（兼容旧版引用方式）
-- 方案里使用的是新版模块写法：lua_translator@*input_count（直接 require lua/input_count.lua）
-- 这里同时把模块绑定为全局变量 input_count，作为旧版写法（lua_translator@input_count）的备用入口，
-- 万一新版写法在当前 librime 版本上不生效，只需把方案补丁里的 @*input_count 改成 @input_count 并重新部署。
local ok, mod = pcall(require, "input_count")
if ok and mod then
  input_count = mod
end
