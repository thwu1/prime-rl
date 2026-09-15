
-- Persistent Sorted Map - Lua 5.4
-- Complete implementation with insertion and Germane-Might deletion.

local RED = 0
local BLACK = 1
local DOUBLE_BLACK = 2
local NEGATIVE_BLACK = -1

-- Sentinel for a deleted black leaf (carries double-black weight)
local BB_LEAF = {DOUBLE_BLACK}

local function make_node(color, left, key, value, right)
    return {color, left, key, value, right}
end

local function default_compare(a, b)
    local ta, tb = type(a), type(b)
    if ta ~= tb then
        local order = {boolean = 0, number = 1, string = 2}
        local oa, ob = order[ta] or 3, order[tb] or 3
        if oa < ob then return -1
        elseif oa > ob then return 1
        else return 0 end
    end
    if ta == "boolean" then
        a = a and 1 or 0
        b = b and 1 or 0
    end
    if a < b then return -1
    elseif a > b then return 1
    else return 0
    end
end

local function blacken(node)
    if not node or rawequal(node, BB_LEAF) then return nil end
    if node[1] == BLACK then return node end
    return make_node(BLACK, node[2], node[3], node[4], node[5])
end

local function redder(node)
    if not node or rawequal(node, BB_LEAF) then return nil end
    return make_node(node[1] - 1, node[2], node[3], node[4], node[5])
end

-- Extended balance: handles insertion (RED-RED) and deletion (DOUBLE_BLACK) cases.
local function balance(color, left, key, value, right)
    -- Cases 1-4: RED-RED violations (generalized to color >= BLACK for deletion)
    if color >= BLACK and left and left[1] == RED
       and left[2] and left[2][1] == RED then
        return make_node(color - 1,
            make_node(BLACK, left[2][2], left[2][3], left[2][4], left[2][5]),
            left[3], left[4],
            make_node(BLACK, left[5], key, value, right))
    end
    if color >= BLACK and left and left[1] == RED
       and left[5] and left[5][1] == RED then
        return make_node(color - 1,
            make_node(BLACK, left[2], left[3], left[4], left[5][2]),
            left[5][3], left[5][4],
            make_node(BLACK, left[5][5], key, value, right))
    end
    if color >= BLACK and right and right[1] == RED
       and right[2] and right[2][1] == RED then
        return make_node(color - 1,
            make_node(BLACK, left, key, value, right[2][2]),
            right[2][3], right[2][4],
            make_node(BLACK, right[2][5], right[3], right[4], right[5]))
    end
    if color >= BLACK and right and right[1] == RED
       and right[5] and right[5][1] == RED then
        return make_node(color - 1,
            make_node(BLACK, left, key, value, right[2]),
            right[3], right[4],
            make_node(BLACK, right[5][2], right[5][3], right[5][4], right[5][5]))
    end
    -- Case 5: DOUBLE_BLACK parent, NEGATIVE_BLACK right child
    if color == DOUBLE_BLACK and right and right[1] == NEGATIVE_BLACK
       and right[2] and right[2][1] == BLACK
       and right[5] and right[5][1] == BLACK then
        return make_node(BLACK,
            make_node(BLACK, left, key, value, right[2][2]),
            right[2][3], right[2][4],
            balance(BLACK, right[2][5], right[3], right[4],
                make_node(RED, right[5][2], right[5][3], right[5][4], right[5][5])))
    end
    -- Case 6: DOUBLE_BLACK parent, NEGATIVE_BLACK left child
    if color == DOUBLE_BLACK and left and left[1] == NEGATIVE_BLACK
       and left[2] and left[2][1] == BLACK
       and left[5] and left[5][1] == BLACK then
        return make_node(BLACK,
            balance(BLACK,
                make_node(RED, left[2][2], left[2][3], left[2][4], left[2][5]),
                left[3], left[4], left[5][2]),
            left[5][3], left[5][4],
            make_node(BLACK, left[5][5], key, value, right))
    end
    return make_node(color, left, key, value, right)
end

local function bubble(color, left, key, value, right)
    if (left and left[1] == DOUBLE_BLACK)
       or (right and right[1] == DOUBLE_BLACK) then
        return balance(color + 1, redder(left), key, value, redder(right))
    end
    return make_node(color, left, key, value, right)
end

local function insert_node(node, key, value, compare)
    if not node then
        return make_node(RED, nil, key, value, nil), true
    end
    local cmp = compare(key, node[3])
    if cmp == 0 then
        if node[4] == value then
            return node, false
        end
        return make_node(node[1], node[2], key, value, node[5]), false
    elseif cmp == -1 then
        local new_left, added = insert_node(node[2], key, value, compare)
        if rawequal(new_left, node[2]) then
            return node, false
        end
        return balance(node[1], new_left, node[3], node[4], node[5]), added
    else
        local new_right, added = insert_node(node[5], key, value, compare)
        if rawequal(new_right, node[5]) then
            return node, false
        end
        return balance(node[1], node[2], node[3], node[4], new_right), added
    end
end

local function search(node, key, compare)
    while node do
        local cmp = compare(key, node[3])
        if cmp == 0 then return node
        elseif cmp == -1 then node = node[2]
        else node = node[5]
        end
    end
    return nil
end

local function find_min(node)
    if node[2] then return find_min(node[2]) end
    return node
end

local remove_node

local function remove_min(node)
    if not node[2] then
        return remove_node(node)
    end
    return bubble(node[1], remove_min(node[2]), node[3], node[4], node[5])
end

remove_node = function(node)
    if not node[2] and not node[5] then
        -- Leaf node
        if node[1] == RED then return nil end
        return BB_LEAF
    elseif not node[5] then
        -- Left child only (must be red child of black parent)
        return make_node(BLACK, node[2][2], node[2][3], node[2][4], node[2][5])
    elseif not node[2] then
        -- Right child only (must be red child of black parent)
        return make_node(BLACK, node[5][2], node[5][3], node[5][4], node[5][5])
    else
        -- Two children: replace with in-order successor
        local min = find_min(node[5])
        return bubble(node[1], node[2], min[3], min[4], remove_min(node[5]))
    end
end

local function delete_node(node, key, compare)
    if not node then return nil end
    local cmp = compare(key, node[3])
    if cmp == -1 then
        local new_left = delete_node(node[2], key, compare)
        if rawequal(new_left, node[2]) then return node end
        return bubble(node[1], new_left, node[3], node[4], node[5])
    elseif cmp == 1 then
        local new_right = delete_node(node[5], key, compare)
        if rawequal(new_right, node[5]) then return node end
        return bubble(node[1], node[2], node[3], node[4], new_right)
    else
        return remove_node(node)
    end
end

local function make_iterator(root)
    local stack = {}
    local n = 0
    local node = root
    while node do
        n = n + 1
        stack[n] = node
        node = node[2]
    end
    return function()
        if n == 0 then return nil end
        local current = stack[n]
        stack[n] = nil
        n = n - 1
        local child = current[5]
        while child do
            n = n + 1
            stack[n] = child
            child = child[2]
        end
        return current[3], current[4]
    end
end

local M = {}

function M.new(compare)
    return {root = nil, count = 0, compare = compare or default_compare}
end

function M.assoc(tree, key, value)
    local raw_root, added = insert_node(tree.root, key, value, tree.compare)
    if rawequal(raw_root, tree.root) then
        return tree
    end
    local new_count = tree.count
    if added then new_count = new_count + 1 end
    return {root = blacken(raw_root), count = new_count, compare = tree.compare}
end

function M.dissoc(tree, key)
    if not tree.root then return tree end
    local new_root = delete_node(tree.root, key, tree.compare)
    if rawequal(new_root, tree.root) then return tree end
    return {root = blacken(new_root), count = tree.count - 1, compare = tree.compare}
end

function M.get(tree, key, not_found)
    local node = search(tree.root, key, tree.compare)
    if node then return node[4] end
    return not_found
end

function M.contains(tree, key)
    return search(tree.root, key, tree.compare) ~= nil
end

function M.count(tree)
    return tree.count
end

function M.pairs(tree)
    return make_iterator(tree.root)
end

function M.from_table(t, compare)
    local m = M.new(compare)
    for k, v in pairs(t) do
        m = M.assoc(m, k, v)
    end
    return m
end

function M.to_table(tree)
    local t = {}
    for k, v in M.pairs(tree) do
        t[k] = v
    end
    return t
end

M._RED = RED
M._BLACK = BLACK

return M
