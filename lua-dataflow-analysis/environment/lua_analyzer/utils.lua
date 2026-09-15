-- utils.lua: Utility functions for the Lua analyzer

local utils = {}

function utils.class()
   local cls = {}
   cls.__index = cls

   setmetatable(cls, {
      __call = function(self, ...)
         local obj = setmetatable({}, cls)
         if cls.__init then
            cls.__init(obj, ...)
         end
         return obj
      end
   })

   return cls
end

function utils.array_to_set(array)
   local set = {}
   for _, v in ipairs(array) do
      set[v] = true
   end
   return set
end

function utils.concat_arrays(arrays)
   local result = {}
   for _, arr in ipairs(arrays) do
      for _, v in ipairs(arr) do
         result[#result + 1] = v
      end
   end
   return result
end

-- Reverse ipairs
function utils.ripairs(t)
   local i = #t + 1
   return function()
      i = i - 1
      if i >= 1 then
         return i, t[i]
      end
   end
end

local Stack = utils.class()

function Stack:__init()
   self.size = 0
end

function Stack:push(value)
   self.size = self.size + 1
   self[self.size] = value
   self.top = value
end

function Stack:pop()
   local value = self[self.size]
   self[self.size] = nil
   self.size = self.size - 1
   self.top = self[self.size]
   return value
end

utils.Stack = Stack

return utils
