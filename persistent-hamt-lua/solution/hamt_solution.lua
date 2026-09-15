
-- Persistent Hash Array Mapped Trie (HAMT) - Lua 5.4
-- Complete implementation.

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

local function mask_fn(h, shift)
    return (h >> shift) & MASK
end

local function bitpos(h, shift)
    return 1 << mask_fn(h, shift)
end

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
    return {type = COLLISION, hash = h, entries = entries}
end

------------------------------------------------------------
-- Core HAMT operations
------------------------------------------------------------

-- Build a bitmap node from two leaves whose hashes differ.
local function create_node(shift, leaf1, leaf2)
    local frag1 = mask_fn(leaf1.hash, shift)
    local frag2 = mask_fn(leaf2.hash, shift)
    if frag1 == frag2 then
        -- Fragments match at this level; recurse deeper
        local child = create_node(shift + BITS, leaf1, leaf2)
        return make_bitmap(1 << frag1, {child})
    else
        local bit1 = 1 << frag1
        local bit2 = 1 << frag2
        local bm = bit1 | bit2
        local children = {}
        children[idx_fn(bm, bit1)] = leaf1
        children[idx_fn(bm, bit2)] = leaf2
        return make_bitmap(bm, children)
    end
end

-- Insert or update. Returns (new_node, added).
local function assoc_node(node, shift, h, key, value)
    if node == nil then
        return make_leaf(h, key, value), true
    end

    if node.type == LEAF then
        if node.hash == h then
            if node.key == key then
                if node.value == value then
                    return node, false
                end
                return make_leaf(h, key, value), false
            else
                return make_collision(h, {
                    {key = node.key, value = node.value},
                    {key = key, value = value},
                }), true
            end
        else
            return create_node(shift, node, make_leaf(h, key, value)), true
        end
    end

    if node.type == COLLISION then
        if node.hash == h then
            for i, entry in ipairs(node.entries) do
                if entry.key == key then
                    if entry.value == value then
                        return node, false
                    end
                    local new_entries = array_copy(node.entries)
                    new_entries[i] = {key = key, value = value}
                    return make_collision(h, new_entries), false
                end
            end
            -- Key not found in collision bucket; append
            local new_entries = array_copy(node.entries)
            new_entries[#new_entries + 1] = {key = key, value = value}
            return make_collision(h, new_entries), true
        else
            -- Different hash: wrap collision in bitmap alongside new leaf
            local frag_c = mask_fn(node.hash, shift)
            local frag_l = mask_fn(h, shift)
            if frag_c == frag_l then
                local child, added = assoc_node(node, shift + BITS, h, key, value)
                return make_bitmap(1 << frag_c, {child}), added
            else
                local leaf = make_leaf(h, key, value)
                local bit_c = 1 << frag_c
                local bit_l = 1 << frag_l
                local bm = bit_c | bit_l
                local children = {}
                children[idx_fn(bm, bit_c)] = node
                children[idx_fn(bm, bit_l)] = leaf
                return make_bitmap(bm, children), true
            end
        end
    end

    if node.type == BITMAP then
        local bit = bitpos(h, shift)
        local i = idx_fn(node.bitmap, bit)
        if (node.bitmap & bit) ~= 0 then
            local child = node.children[i]
            local new_child, added = assoc_node(child, shift + BITS, h, key, value)
            if child == new_child then
                return node, false
            end
            return make_bitmap(node.bitmap,
                               array_copy_and_set(node.children, i, new_child)),
                   added
        else
            local new_children = array_copy_and_insert(
                node.children, i, make_leaf(h, key, value))
            return make_bitmap(node.bitmap | bit, new_children), true
        end
    end

    error("assoc_node: unknown node type " .. tostring(node.type))
end

-- Delete. Returns new_node or nil.
local function dissoc_node(node, shift, h, key)
    if node == nil then
        return nil
    end

    if node.type == LEAF then
        if node.key == key then
            return nil
        end
        return node
    end

    if node.type == COLLISION then
        if node.hash ~= h then
            return node
        end
        local found_idx = nil
        for i, entry in ipairs(node.entries) do
            if entry.key == key then
                found_idx = i
                break
            end
        end
        if found_idx == nil then
            return node
        end
        if #node.entries == 2 then
            local remaining = node.entries[found_idx == 1 and 2 or 1]
            return make_leaf(h, remaining.key, remaining.value)
        end
        return make_collision(h, array_copy_and_remove(node.entries, found_idx))
    end

    if node.type == BITMAP then
        local bit = bitpos(h, shift)
        if (node.bitmap & bit) == 0 then
            return node
        end
        local i = idx_fn(node.bitmap, bit)
        local child = node.children[i]
        local new_child = dissoc_node(child, shift + BITS, h, key)
        if child == new_child then
            return node
        end
        if new_child == nil then
            local new_bitmap = node.bitmap & (~bit)
            if new_bitmap == 0 then
                return nil
            end
            local new_children = array_copy_and_remove(node.children, i)
            if #new_children == 1
               and (new_children[1].type == LEAF
                    or new_children[1].type == COLLISION) then
                return new_children[1]
            end
            return make_bitmap(new_bitmap, new_children)
        end
        return make_bitmap(node.bitmap,
                           array_copy_and_set(node.children, i, new_child))
    end

    error("dissoc_node: unknown node type " .. tostring(node.type))
end

-- Lookup. Returns (value, found).
local function get_node(node, shift, h, key)
    if node == nil then
        return nil, false
    end

    if node.type == LEAF then
        if node.key == key then
            return node.value, true
        end
        return nil, false
    end

    if node.type == COLLISION then
        if node.hash ~= h then
            return nil, false
        end
        for _, entry in ipairs(node.entries) do
            if entry.key == key then
                return entry.value, true
            end
        end
        return nil, false
    end

    if node.type == BITMAP then
        local bit = bitpos(h, shift)
        if (node.bitmap & bit) == 0 then
            return nil, false
        end
        local i = idx_fn(node.bitmap, bit)
        return get_node(node.children[i], shift + BITS, h, key)
    end

    error("get_node: unknown node type " .. tostring(node.type))
end

-- Count entries in subtree.
local function count_node(node)
    if node == nil then return 0 end
    if node.type == LEAF then return 1 end
    if node.type == COLLISION then return #node.entries end
    if node.type == BITMAP then
        local total = 0
        for _, child in ipairs(node.children) do
            total = total + count_node(child)
        end
        return total
    end
    error("count_node: unknown node type")
end

-- Coroutine-based iterator.
local function iter_node(node)
    if node == nil then return end
    if node.type == LEAF then
        coroutine.yield(node.key, node.value)
    elseif node.type == COLLISION then
        for _, entry in ipairs(node.entries) do
            coroutine.yield(entry.key, entry.value)
        end
    elseif node.type == BITMAP then
        for _, child in ipairs(node.children) do
            iter_node(child)
        end
    end
end

local function make_iterator(node)
    if node == nil then
        return function() return nil end
    end
    local co = coroutine.create(function() iter_node(node) end)
    return function()
        if coroutine.status(co) == "dead" then return nil end
        local ok, k, v = coroutine.resume(co)
        if ok and k ~= nil then
            return k, v
        end
        return nil
    end
end

------------------------------------------------------------
-- Public API
------------------------------------------------------------
local M = {}

function M.new()
    return {root = nil, count = 0}
end

function M.assoc(map, key, value)
    local h = hash(key)
    local new_root, added = assoc_node(map.root, 0, h, key, value)
    if map.root == new_root then
        return map
    end
    return {root = new_root, count = map.count + (added and 1 or 0)}
end

function M.dissoc(map, key)
    if map.root == nil then return map end
    local h = hash(key)
    local new_root = dissoc_node(map.root, 0, h, key)
    if map.root == new_root then
        return map
    end
    return {root = new_root, count = map.count - 1}
end

function M.get(map, key, not_found)
    if map.root == nil then return not_found end
    local value, found = get_node(map.root, 0, hash(key), key)
    if found then return value end
    return not_found
end

function M.contains(map, key)
    if map.root == nil then return false end
    local _, found = get_node(map.root, 0, hash(key), key)
    return found
end

function M.count(map)
    return map.count
end

function M.pairs(map)
    return make_iterator(map.root)
end

function M.from_table(t)
    local m = M.new()
    for k, v in pairs(t) do
        m = M.assoc(m, k, v)
    end
    return m
end

function M.to_table(map)
    local t = {}
    for k, v in M.pairs(map) do
        t[k] = v
    end
    return t
end

-- Exports for testing
M._hash = hash
M._popcount = popcount
M._BITS = BITS
M._WIDTH = WIDTH
M._MASK = MASK

return M
