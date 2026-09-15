-- decoder.lua: Simple source decoder (UTF-8 passthrough)
-- Wraps a source string to provide the interface expected by lexer/parser.

local decoder = {}

local DecodedString = {}
DecodedString.__index = DecodedString

function DecodedString:get_length()
   return #self.str
end

function DecodedString:get_codepoint(offset)
   if offset > #self.str or offset < 1 then
      return nil
   end
   return string.byte(self.str, offset)
end

function DecodedString:get_substring(start, stop)
   return self.str:sub(start, stop)
end

function DecodedString:get_printable_substring(start, stop)
   return self.str:sub(start, stop)
end

function DecodedString:find(pattern, init)
   return self.str:find(pattern, init)
end

function decoder.decode(source_bytes)
   return setmetatable({str = source_bytes}, DecodedString)
end

return decoder
