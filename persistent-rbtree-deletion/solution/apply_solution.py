#!/usr/bin/env python3

"""
Construct the complete persistent red-black tree implementation
with deletion support and write it to /app/rbtree.lua.
"""


def build_header():
    return """\
-- rbtree.lua: Persistent Red-Black Tree (complete implementation)
--
-- Immutable red-black tree with O(log n) insert, delete, and search.
-- Deletion uses extended node colors for rebalancing.

"""


def build_constants():
    return """\
local RED = 0
local BLACK = 1
local DOUBLE_BLACK = 2
local NEGATIVE_BLACK = -1

local BB_LEAF = {DOUBLE_BLACK}

local function make_node(color, left, key, value, right)
    return {color, left, key, value, right}
end
"""


def build_redder():
    return """\
local function redder(node)
    if node == nil or node == BB_LEAF then return nil end
    return make_node(node[1] - 1, node[2], node[3], node[4], node[5])
end
"""


def build_blacken():
    return """\
local function blacken(node)
    if node == nil or node == BB_LEAF then return nil end
    if node[1] == BLACK then return node end
    return make_node(BLACK, node[2], node[3], node[4], node[5])
end
"""


def build_balance():
    return """\
local function balance(color, left, key, value, right)
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
    if color == DOUBLE_BLACK and right and right[1] == NEGATIVE_BLACK
       and right[2] and right[2][1] == BLACK
       and right[5] and right[5][1] == BLACK then
        return make_node(BLACK,
            make_node(BLACK, left, key, value, right[2][2]),
            right[2][3], right[2][4],
            balance(BLACK, right[2][5], right[3], right[4],
                make_node(RED, right[5][2], right[5][3], right[5][4], right[5][5])))
    end
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
"""


def build_bubble():
    return """\
local function bubble(color, left, key, value, right)
    if (left and left[1] == DOUBLE_BLACK)
       or (right and right[1] == DOUBLE_BLACK) then
        return balance(color + 1, redder(left), key, value, redder(right))
    end
    return make_node(color, left, key, value, right)
end
"""


def build_insertion():
    return """\
local function insert_node(node, key, value)
    if node == nil then
        return make_node(RED, nil, key, value, nil), true
    end
    if key < node[3] then
        local new_left, added = insert_node(node[2], key, value)
        if new_left == node[2] then return node, false end
        return balance(node[1], new_left, node[3], node[4], node[5]), added
    elseif key > node[3] then
        local new_right, added = insert_node(node[5], key, value)
        if new_right == node[5] then return node, false end
        return balance(node[1], node[2], node[3], node[4], new_right), added
    else
        if node[4] == value then return node, false end
        return make_node(node[1], node[2], key, value, node[5]), false
    end
end
"""


def build_search():
    return """\
local function search(root, key)
    local node = root
    while node and node ~= BB_LEAF do
        if key < node[3] then
            node = node[2]
        elseif key > node[3] then
            node = node[5]
        else
            return node[4]
        end
    end
    return nil
end

local function find_min(node)
    if node[2] then return find_min(node[2]) end
    return node
end
"""


def build_deletion():
    return """\
local remove_node_fn

local function remove_min(node)
    if not node[2] then
        return remove_node_fn(node)
    end
    return bubble(node[1], remove_min(node[2]), node[3], node[4], node[5])
end

remove_node_fn = function(node)
    if not node[2] and not node[5] then
        if node[1] == RED then return nil end
        return BB_LEAF
    end
    if not node[5] then
        return make_node(BLACK, node[2][2], node[2][3], node[2][4], node[2][5])
    end
    if not node[2] then
        return make_node(BLACK, node[5][2], node[5][3], node[5][4], node[5][5])
    end
    local min = find_min(node[5])
    return bubble(node[1], node[2], min[3], min[4], remove_min(node[5]))
end

local function delete_node(node, key)
    if node == nil then return node end
    if key < node[3] then
        local new_left = delete_node(node[2], key)
        if new_left == node[2] then return node end
        return bubble(node[1], new_left, node[3], node[4], node[5])
    elseif key > node[3] then
        local new_right = delete_node(node[5], key)
        if new_right == node[5] then return node end
        return bubble(node[1], node[2], node[3], node[4], new_right)
    else
        return remove_node_fn(node)
    end
end
"""


def build_traversal_and_validation():
    return """\
local function collect_sorted(node, result)
    if node == nil or node == BB_LEAF then return end
    collect_sorted(node[2], result)
    result[#result + 1] = {node[3], node[4]}
    collect_sorted(node[5], result)
end

local function check_invariants(node, parent_color)
    if node == nil then return true, 1, nil end
    if node == BB_LEAF then return false, 0, "BB_LEAF in final tree" end
    local color = node[1]
    if color == DOUBLE_BLACK then
        return false, 0, "DOUBLE_BLACK node in final tree"
    end
    if color == NEGATIVE_BLACK then
        return false, 0, "NEGATIVE_BLACK node in final tree"
    end
    if color == RED and parent_color == RED then
        return false, 0, "red-red violation at key " .. tostring(node[3])
    end
    local ok_l, bh_l, err_l = check_invariants(node[2], color)
    if not ok_l then return false, 0, err_l end
    local ok_r, bh_r, err_r = check_invariants(node[5], color)
    if not ok_r then return false, 0, err_r end
    if bh_l ~= bh_r then
        return false, 0, string.format(
            "black height mismatch at key %s: left=%d right=%d",
            tostring(node[3]), bh_l, bh_r)
    end
    return true, bh_l + (color == BLACK and 1 or 0), nil
end

local function check_ordering(node)
    if node == nil or node == BB_LEAF then return true, nil end
    if node[2] then
        local ok, err = check_ordering(node[2])
        if not ok then return false, err end
        local n = node[2]
        while n[5] do n = n[5] end
        if not (n[3] < node[3]) then
            return false, tostring(n[3]) .. " not < " .. tostring(node[3])
        end
    end
    if node[5] then
        local ok, err = check_ordering(node[5])
        if not ok then return false, err end
        local n = node[5]
        while n[2] do n = n[2] end
        if not (node[3] < n[3]) then
            return false, tostring(node[3]) .. " not < " .. tostring(n[3])
        end
    end
    return true, nil
end
"""


def build_public_api():
    return """\
local rbtree = {}

function rbtree.new()
    return {root = nil, count = 0}
end

function rbtree.insert(tree, key, value)
    local new_root, added = insert_node(tree.root, key, value)
    new_root = blacken(new_root)
    local new_count = tree.count
    if added then new_count = new_count + 1 end
    return {root = new_root, count = new_count}
end

function rbtree.delete(tree, key)
    if tree.root == nil then return tree end
    local new_root = delete_node(tree.root, key)
    if new_root == tree.root then return tree end
    new_root = blacken(new_root)
    return {root = new_root, count = tree.count - 1}
end

function rbtree.search(tree, key)
    return search(tree.root, key)
end

function rbtree.contains(tree, key)
    local node = tree.root
    while node and node ~= BB_LEAF do
        if key < node[3] then
            node = node[2]
        elseif key > node[3] then
            node = node[5]
        else
            return true
        end
    end
    return false
end

function rbtree.count(tree)
    return tree.count
end

function rbtree.to_sorted_list(tree)
    local result = {}
    collect_sorted(tree.root, result)
    return result
end

function rbtree.validate(tree)
    if tree.root == nil then return true, nil end
    if tree.root[1] ~= BLACK then
        return false, "root is not black"
    end
    local ok, _, err = check_invariants(tree.root, BLACK)
    if not ok then return false, err end
    return check_ordering(tree.root)
end

return rbtree
"""


def main():
    sections = [
        build_header(),
        build_constants(),
        build_redder(),
        build_blacken(),
        build_balance(),
        build_bubble(),
        build_insertion(),
        build_search(),
        build_deletion(),
        build_traversal_and_validation(),
        build_public_api(),
    ]
    complete_source = "\n".join(sections)
    with open("/app/rbtree.lua", "w") as f:
        f.write(complete_source)
    print("Solution applied to /app/rbtree.lua")


if __name__ == "__main__":
    main()
