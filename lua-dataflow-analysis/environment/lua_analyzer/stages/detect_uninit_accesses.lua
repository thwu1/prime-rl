-- detect_uninit_accesses.lua: Detect accesses to uninitialized local variables
--
-- Warning codes:
--   321: accessing uninitialized variable
--   341: mutating uninitialized variable
--
-- This stage is incomplete and needs a full implementation.

local stage = {}

stage.warnings = {
   ["321"] = {message_format = "accessing uninitialized variable {name!}", fields = {"name"}},
   ["341"] = {message_format = "mutating uninitialized variable {name!}", fields = {"name"}}
}

function stage.run(chstate)
   -- Stub: needs implementation.
end

return stage
