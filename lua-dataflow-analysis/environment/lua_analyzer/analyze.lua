-- analyze.lua: Main entry point for the Lua static analyzer
-- Usage: lua analyze.lua <source_file>
-- Outputs a JSON array of uninitialized-access warnings sorted by (line, column).
--

-- Set up package path to find our modules
local script_dir = arg[0]:match("(.*/)")  or "./"
package.path = script_dir .. "?.lua;" .. script_dir .. "?/init.lua;" .. package.path

local check_state = require "lua_analyzer.check_state"
local parse_stage = require "lua_analyzer.stages.parse"
local linearize_stage = require "lua_analyzer.stages.linearize"
local resolve_locals_stage = require "lua_analyzer.stages.resolve_locals"
local detect_uninit_stage = require "lua_analyzer.stages.detect_uninit_accesses"

local function read_file(path)
   local f = io.open(path, "rb")
   if not f then
      io.stderr:write("Error: cannot open file: " .. path .. "\n")
      os.exit(1)
   end
   local content = f:read("*a")
   f:close()
   return content
end

local function sort_warnings(warnings)
   table.sort(warnings, function(a, b)
      if a.line ~= b.line then return a.line < b.line end
      if a.column ~= b.column then return a.column < b.column end
      return a.code < b.code
   end)
end

local function escape_json_string(s)
   return s:gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('\n', '\\n'):gsub('\r', '\\r'):gsub('\t', '\\t')
end

local function warnings_to_json(warnings)
   local parts = {}
   for _, w in ipairs(warnings) do
      local obj = string.format(
         '{"code":"%s","name":"%s","line":%d,"column":%d}',
         escape_json_string(w.code),
         escape_json_string(w.name),
         w.line,
         w.column
      )
      parts[#parts + 1] = obj
   end
   return "[" .. table.concat(parts, ",") .. "]"
end

-- Main
if #arg < 1 then
   io.stderr:write("Usage: lua analyze.lua <source_file>\n")
   os.exit(1)
end

local source = read_file(arg[1])
local chstate = check_state.new(source)

-- Run the pipeline: parse -> linearize -> resolve_locals -> detect_uninit_accesses
local ok, err = pcall(function()
   parse_stage.run(chstate)
   linearize_stage.run(chstate)
   resolve_locals_stage.run(chstate)
   detect_uninit_stage.run(chstate)
end)

if not ok then
   -- If it's a syntax error, output empty warnings
   if type(err) == "table" and err.msg then
      io.stderr:write("Syntax error: " .. err.msg .. " at line " .. tostring(err.line) .. "\n")
      print("[]")
      os.exit(0)
   else
      io.stderr:write("Error: " .. tostring(err) .. "\n")
      os.exit(1)
   end
end

-- Filter to only 321/341 warnings
local filtered = {}
for _, w in ipairs(chstate.warnings) do
   if w.code == "321" or w.code == "341" then
      filtered[#filtered + 1] = w
   end
end

sort_warnings(filtered)
print(warnings_to_json(filtered))
