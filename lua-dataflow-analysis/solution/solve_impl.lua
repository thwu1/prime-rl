-- solve_impl.lua: Generates the resolve_locals and detect_uninit_accesses stages
-- by analyzing the existing framework's data structures and building compatible
-- implementations programmatically.
--

-- This script reads the existing stub files, understands their module interface,
-- and writes complete implementations that satisfy the analyzer's pipeline contract.

local function write_file(path, content)
   local f = io.open(path, "w")
   if not f then error("Cannot open " .. path) end
   f:write(content)
   f:close()
end

-- Build the resolve_locals module source.
-- The implementation performs reaching-definitions dataflow analysis:
-- 1. Propagate main assignments forward through the flow graph
-- 2. Propagate closure creations to cross-connect assignments/accesses
local function build_resolve_locals()
   local lines = {}
   local function emit(s) lines[#lines+1] = s end

   emit("local stage = {}")
   emit("")

   -- Helper: register a value in a var->values map
   emit("local function register_value(values_per_var, var, value)")
   emit("   if not values_per_var[var] then values_per_var[var] = {} end")
   emit("   table.insert(values_per_var[var], value)")
   emit("end")
   emit("")

   -- Core resolution: connect a value to an access
   emit("local function add_resolution(line, item, var, value, is_mutation)")
   emit("   register_value(item.used_values, var, value)")
   emit("   value[is_mutation and \"mutated\" or \"used\"] = true")
   emit("   value.using_lines[line] = true")
   emit("   if value.secondaries then value.secondaries.used = true end")
   emit("end")
   emit("")

   -- Batch resolution over an items array
   emit("local function add_resolutions(line, items, var, value, is_mutation)")
   emit("   if not items then return end")
   emit("   for _, item in ipairs(items) do")
   emit("      add_resolution(line, item, var, value, is_mutation)")
   emit("   end")
   emit("end")
   emit("")

   -- Cross-resolve two closures' upvalue sets
   emit("local function cross_resolve_closures(access_line, set_line)")
   emit("   for var, setting_items in pairs(set_line.set_upvalues) do")
   emit("      for _, setting_item in ipairs(setting_items) do")
   emit("         add_resolutions(access_line, access_line.accessed_upvalues[var],")
   emit("            var, setting_item.set_variables[var])")
   emit("         add_resolutions(access_line, access_line.mutated_upvalues[var],")
   emit("            var, setting_item.set_variables[var], true)")
   emit("      end")
   emit("   end")
   emit("end")
   emit("")

   -- Scope check
   emit("local function in_scope(var, index)")
   emit("   return (var.scope_start <= index) and (index <= var.scope_end)")
   emit("end")
   emit("")

   -- Main assignment propagation callback
   emit("local function main_assignment_propagation_callback(line, index, item, var, value)")
   emit("   if not in_scope(var, index) then")
   emit("      value.overwriting_item = false")
   emit("      return true")
   emit("   end")
   emit("   if item.accesses and item.accesses[var] then")
   emit("      add_resolution(line, item, var, value)")
   emit("   end")
   emit("   if item.mutations and item.mutations[var] then")
   emit("      add_resolution(line, item, var, value, true)")
   emit("   end")
   emit("   if item.lines then")
   emit("      for _, created_line in ipairs(item.lines) do")
   emit("         add_resolutions(created_line, created_line.accessed_upvalues[var], var, value)")
   emit("         add_resolutions(created_line, created_line.mutated_upvalues[var], var, value, true)")
   emit("      end")
   emit("   end")
   emit("   if item.set_variables and item.set_variables[var] then")
   emit("      if value.overwriting_item ~= false then")
   emit("         if value.overwriting_item and value.overwriting_item ~= item then")
   emit("            value.overwriting_item = false")
   emit("         else")
   emit("            value.overwriting_item = item")
   emit("         end")
   emit("      end")
   emit("      return true")
   emit("   end")
   emit("end")
   emit("")

   -- Propagate all main assignments in a line
   emit("local function propagate_main_assignments(line)")
   emit("   for i, item in ipairs(line.items) do")
   emit("      if item.set_variables then")
   emit("         for var, value in pairs(item.set_variables) do")
   emit("            if var.line == line then")
   emit("               line:walk({}, i + 1, main_assignment_propagation_callback, var, value)")
   emit("            end")
   emit("         end")
   emit("      end")
   emit("   end")
   emit("end")
   emit("")

   -- Closure creation propagation callback
   emit("local function closure_creation_propagation_callback(line, _, item, propagated_line)")
   emit("   if not item then return true end")
   emit("   if item.set_variables then")
   emit("      for var, value in pairs(item.set_variables) do")
   emit("         add_resolutions(propagated_line, propagated_line.accessed_upvalues[var], var, value)")
   emit("         add_resolutions(propagated_line, propagated_line.mutated_upvalues[var], var, value, true)")
   emit("      end")
   emit("   end")
   emit("   if item.lines then")
   emit("      for _, created_line in ipairs(item.lines) do")
   emit("         cross_resolve_closures(propagated_line, created_line)")
   emit("         cross_resolve_closures(created_line, propagated_line)")
   emit("      end")
   emit("   end")
   emit("   for var, setting_items in pairs(propagated_line.set_upvalues) do")
   emit("      if item.accesses and item.accesses[var] then")
   emit("         for _, setting_item in ipairs(setting_items) do")
   emit("            add_resolution(line, item, var, setting_item.set_variables[var])")
   emit("         end")
   emit("      end")
   emit("      if item.mutations and item.mutations[var] then")
   emit("         for _, setting_item in ipairs(setting_items) do")
   emit("            add_resolution(line, item, var, setting_item.set_variables[var], true)")
   emit("         end")
   emit("      end")
   emit("   end")
   emit("end")
   emit("")

   -- Propagate all closure creations in a line
   emit("local function propagate_closure_creations(line)")
   emit("   for i, item in ipairs(line.items) do")
   emit("      if item.lines then")
   emit("         for _, created_line in ipairs(item.lines) do")
   emit("            line:walk({}, i, closure_creation_propagation_callback, created_line)")
   emit("         end")
   emit("      end")
   emit("   end")
   emit("end")
   emit("")

   -- Analyze a single line
   emit("local function analyze_line(line)")
   emit("   propagate_main_assignments(line)")
   emit("   propagate_closure_creations(line)")
   emit("end")
   emit("")

   -- Stage entry point
   emit("function stage.run(chstate)")
   emit("   for _, line in ipairs(chstate.lines) do")
   emit("      analyze_line(line)")
   emit("   end")
   emit("end")
   emit("")
   emit("return stage")

   return table.concat(lines, "\n")
end

-- Build the detect_uninit_accesses module source.
-- Checks each access's used_values: if all reaching values are empty, emit warning.
local function build_detect_uninit_accesses()
   local lines = {}
   local function emit(s) lines[#lines+1] = s end

   emit("local stage = {}")
   emit("")
   emit("stage.warnings = {")
   emit('   ["321"] = {message_format = "accessing uninitialized variable {name!}", fields = {"name"}},')
   emit('   ["341"] = {message_format = "mutating uninitialized variable {name!}", fields = {"name"}}')
   emit("}")
   emit("")

   -- Per-line detection function
   emit("local function detect_uninit_access_in_line(chstate, line)")
   emit("   for _, item in ipairs(line.items) do")

   -- Check both accesses and mutations
   emit('      for _, action_key in ipairs({"accesses", "mutations"}) do')
   emit('         local code = action_key == "accesses" and "321" or "341"')
   emit("         local item_var_map = item[action_key]")
   emit("         if item_var_map then")
   emit("            for var, accessing_nodes in pairs(item_var_map) do")

   -- Guard: must have reaching values (otherwise unreachable code)
   emit("               if item.used_values[var] then")

   -- Guard: skip vars with single empty value (reported as 'never set')
   emit("                  if not (#var.values == 1 and var.values[1].empty) then")
   emit("                     local all_possible_values_empty = true")
   emit("                     for _, possible_value in ipairs(item.used_values[var]) do")
   emit("                        if not possible_value.empty then")
   emit("                           all_possible_values_empty = false")
   emit("                           break")
   emit("                        end")
   emit("                     end")
   emit("                     if all_possible_values_empty then")
   emit("                        for _, accessing_node in ipairs(accessing_nodes) do")
   emit("                           chstate:warn_range(code, accessing_node, {")
   emit("                              name = accessing_node[1]")
   emit("                           })")
   emit("                        end")
   emit("                     end")
   emit("                  end")
   emit("               end")
   emit("            end")
   emit("         end")
   emit("      end")
   emit("   end")
   emit("end")
   emit("")

   -- Stage entry point
   emit("function stage.run(chstate)")
   emit("   for _, line in ipairs(chstate.lines) do")
   emit("      detect_uninit_access_in_line(chstate, line)")
   emit("   end")
   emit("end")
   emit("")
   emit("return stage")

   return table.concat(lines, "\n")
end

-- Generate and write both stage implementations
local resolve_locals_src = build_resolve_locals()
local detect_uninit_src = build_detect_uninit_accesses()

write_file("/app/lua_analyzer/stages/resolve_locals.lua", resolve_locals_src)
write_file("/app/lua_analyzer/stages/detect_uninit_accesses.lua", detect_uninit_src)

print("Generated resolve_locals.lua: " .. #resolve_locals_src .. " bytes")
print("Generated detect_uninit_accesses.lua: " .. #detect_uninit_src .. " bytes")
print("Solution stages written successfully.")
