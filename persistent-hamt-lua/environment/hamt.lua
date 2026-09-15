
-- Persistent Hash Array Mapped Trie (HAMT) - Lua 5.4
-- See /app/spec.md for algorithm specification.

local BITS = 5
local WIDTH = 32
local MASK = WIDTH - 1
local HASH_BITS = 30

-- Node type tags
local LEAF = 1
local BITMAP = 2
local COLLISION = 3

------------------------------------------------------------
-- Hash function (djb2, deterministic, 30-bit output)
------------------------------------------------------------
local function hash(key)
    if type(key) == "number" then
        if key ~= key then return hash("NaN") end
        if key == 0 then return hash("0") end
        if key == math.floor(key) then
            return hash(tostring(math.floor(key)))
        end
        return hash(tostring(key))
    elseif type(key) == "string" then
        local h = 5381
        for i = 1, #key do
            h = ((h * 33) + key:byte(i)) & 0x3FFFFFFF
        end
        return h
    elseif type(key) == "boolean" then
        return key and hash("true") or hash("false")
    else
        return hash(tostring(key))
    end
end

------------------------------------------------------------
-- Bit manipulation helpers
------------------------------------------------------------
local function popcount(x)
    x = x - ((x >> 1) & 0x55555555)
    x = (x & 0x33333333) + ((x >> 2) & 0x33333333)
    x = (x + (x >> 4)) & 0x0F0F0F0F
    return ((x * 0x01010101) >> 24) & 0xFF
end

-- Extract BITS-wide fragment from hash at given shift level
local function mask_fn(h, shift)
    return (h >> shift) & MASK
end

-- Compute the single-bit position for hash fragment at shift level
local function bitpos(h, shift)
    return 1 << mask_fn(h, shift)
end

-- Compute compact-array index from bitmap and target bit
local function idx_fn(bitmap, bit)
    return popcount(bitmap & (bit - 1)) + 1
end

------------------------------------------------------------
-- Array helpers (copy-on-write)
------------------------------------------------------------
local function array_copy(arr, len)
    local new = {}
    for i = 1, (len or #arr) do new[i] = arr[i] end
    return new
end

local function array_copy_and_set(arr, i, val)
    local new = array_copy(arr)
    new[i] = val
    return new
end

local function array_copy_and_insert(arr, i, val)
    local new = {}
    for j = 1, i - 1 do new[j] = arr[j] end
    new[i] = val
    for j = i, #arr do new[j + 1] = arr[j] end
    return new
end

local function array_copy_and_remove(arr, i)
    local new = {}
    for j = 1, i - 1 do new[j] = arr[j] end
    for j = i + 1, #arr do new[j - 1] = arr[j] end
    return new
end

------------------------------------------------------------
-- Node constructors
------------------------------------------------------------
local function make_leaf(h, key, value)
    return {type = LEAF, hash = h, key = key, value = value}
end

local function make_bitmap(bm, children)
    return {type = BITMAP, bitmap = bm, children = children}
end

local function make_collision(h, entries)
    -- entries: array of {key=k, value=v} tables
    return {type = COLLISION, hash = h, entries = entries}
end

------------------------------------------------------------
-- TODO: Implement core HAMT operations below
------------------------------------------------------------

-- Construct a bitmap node from two leaves with different hashes.
local function create_node(shift, leaf1, leaf2)
    error("create_node: not implemented")
end

-- Insert or update key in trie. Returns (new_node, was_added).
local function assoc_node(node, shift, h, key, value)
    error("assoc_node: not implemented")
end

-- Remove key from trie. Returns new_node (nil if now empty).
local function dissoc_node(node, shift, h, key)
    error("dissoc_node: not implemented")
end

-- Look up key in trie. Returns (value, found_boolean).
local function get_node(node, shift, h, key)
    error("get_node: not implemented")
end

-- Count all entries in the node subtree.
local function count_node(node)
    error("count_node: not implemented")
end

-- Return a Lua iterator function yielding (key, value) pairs.
local function make_iterator(node)
    error("make_iterator: not implemented")
end

------------------------------------------------------------
-- Public API
------------------------------------------------------------
local M = {}

function M.new()
    return {root = nil, count = 0}
end

function M.assoc(map, key, value)
    -- TODO: compute hash, call assoc_node, return new map
    error("M.assoc: not implemented")
end

function M.dissoc(map, key)
    -- TODO: compute hash, call dissoc_node, return new map
    error("M.dissoc: not implemented")
end

function M.get(map, key, not_found)
    -- TODO: compute hash, call get_node
    error("M.get: not implemented")
end

function M.contains(map, key)
    -- TODO: check if key exists
    error("M.contains: not implemented")
end

function M.count(map)
    return map.count
end

function M.pairs(map)
    -- TODO: return iterator over all entries
    error("M.pairs: not implemented")
end

function M.from_table(t)
    -- TODO: build map from Lua table
    error("M.from_table: not implemented")
end

function M.to_table(map)
    -- TODO: convert map to Lua table
    error("M.to_table: not implemented")
end

-- Exports for testing
M._hash = hash
M._popcount = popcount
M._BITS = BITS
M._WIDTH = WIDTH
M._MASK = MASK

return M
