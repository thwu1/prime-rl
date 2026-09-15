#!/usr/bin/env python3
"""
Fix the B+ tree sorted set implementation.

Fixes applied:
1. Leaf split: promote keys[mid] (first key of right half), not keys[mid-1].
2. Leaf merge: update the leaf doubly-linked list so the orphaned right
   node is bypassed.
3. zrangebyscore: remove the off-by-one that skips the first matching entry.
4. Subtree-size maintenance: increment/decrement along root–leaf path on
   every insert/delete, and recompute during split/merge/borrow.
5. zrank: implement O(log n) rank query using augmented subtree sizes.
"""


"""
B+ Tree Sorted Set — corrected implementation.
"""

import json
from typing import Optional, List, Tuple, Dict
from bisect import bisect_left, bisect_right


class BPNode:
    __slots__ = (
        "is_leaf", "order", "keys", "children",
        "parent", "next_leaf", "prev_leaf", "subtree_size",
    )

    def __init__(self, is_leaf=False, order=64):
        self.is_leaf = is_leaf
        self.order = order
        self.keys = []
        self.children = []
        self.parent = None
        self.next_leaf = None
        self.prev_leaf = None
        self.subtree_size = 0


class BPTreeZSet:
    def __init__(self, order=64):
        if order < 4:
            raise ValueError("order must be >= 4")
        self.order = order
        self.root = BPNode(is_leaf=True, order=order)
        self.member_scores = {}
        self._size = 0
        self._node_count = 1

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    def zadd(self, member, score):
        is_new = member not in self.member_scores
        if not is_new:
            old_score = self.member_scores[member]
            if old_score == score:
                return False
            self._remove_entry(old_score, member)
            self._size -= 1
        self.member_scores[member] = score
        self._insert_into_tree((score, member))
        self._size += 1
        return is_new

    def zscore(self, member):
        return self.member_scores.get(member)

    def zrem(self, member):
        if member not in self.member_scores:
            return False
        score = self.member_scores.pop(member)
        self._remove_entry(score, member)
        self._size -= 1
        return True

    def zrank(self, member):
        if member not in self.member_scores:
            return -1
        score = self.member_scores[member]
        key = (score, member)
        rank = 0
        node = self.root
        while not node.is_leaf:
            pos = bisect_right(node.keys, key)
            for i in range(pos):
                rank += node.children[i].subtree_size
            node = node.children[pos]
        pos = bisect_left(node.keys, key)
        rank += pos
        return rank

    def zrange(self, start, stop):
        node = self.root
        while not node.is_leaf:
            node = node.children[0]
        results = []
        rank = 0
        while node is not None:
            for score, member in node.keys:
                if rank > stop:
                    return results
                if rank >= start:
                    results.append((member, score))
                rank += 1
            node = node.next_leaf
        return results

    def zrangebyscore(self, min_score, max_score):
        search_key = (min_score, "")
        leaf = self._find_leaf(search_key)
        pos = bisect_left(leaf.keys, search_key)
        # FIX: start from pos directly — no off-by-one
        results = []
        node = leaf
        while node is not None:
            while pos < len(node.keys):
                score, member = node.keys[pos]
                if score > max_score:
                    return results
                results.append((member, score))
                pos += 1
            node = node.next_leaf
            pos = 0
        return results

    def zcard(self):
        return self._size

    def serialize(self):
        entries = []
        node = self.root
        while not node.is_leaf:
            node = node.children[0]
        while node is not None:
            for score, member in node.keys:
                entries.append({"m": member, "s": score})
            node = node.next_leaf
        return json.dumps({"entries": entries, "order": self.order})

    @classmethod
    def deserialize(cls, data):
        obj = json.loads(data)
        zset = cls(order=obj["order"])
        for entry in obj["entries"]:
            zset.zadd(entry["m"], entry["s"])
        return zset

    # ------------------------------------------------------------------ #
    #  Navigation                                                         #
    # ------------------------------------------------------------------ #

    def _find_leaf(self, key):
        node = self.root
        while not node.is_leaf:
            pos = bisect_right(node.keys, key)
            node = node.children[pos]
        return node

    # ------------------------------------------------------------------ #
    #  Insertion                                                          #
    # ------------------------------------------------------------------ #

    def _insert_into_tree(self, key):
        leaf = self._find_leaf(key)
        pos = bisect_left(leaf.keys, key)
        leaf.keys.insert(pos, key)
        # FIX: update subtree sizes along the path to root
        node = leaf
        while node is not None:
            node.subtree_size += 1
            node = node.parent
        if len(leaf.keys) >= self.order:
            self._split_leaf(leaf)

    def _split_leaf(self, leaf):
        mid = len(leaf.keys) // 2
        new_leaf = BPNode(is_leaf=True, order=self.order)
        self._node_count += 1

        # FIX: promote keys[mid] — first key of the new right leaf
        promote_key = leaf.keys[mid]

        new_leaf.keys = leaf.keys[mid:]
        leaf.keys = leaf.keys[:mid]

        # FIX: set subtree sizes for the two halves
        leaf.subtree_size = len(leaf.keys)
        new_leaf.subtree_size = len(new_leaf.keys)

        new_leaf.next_leaf = leaf.next_leaf
        if leaf.next_leaf is not None:
            leaf.next_leaf.prev_leaf = new_leaf
        leaf.next_leaf = new_leaf
        new_leaf.prev_leaf = leaf

        self._insert_into_parent(leaf, promote_key, new_leaf)

    def _split_internal(self, node):
        mid = len(node.keys) // 2
        new_node = BPNode(is_leaf=False, order=self.order)
        self._node_count += 1

        promote_key = node.keys[mid]

        new_node.keys = node.keys[mid + 1:]
        new_node.children = node.children[mid + 1:]
        node.keys = node.keys[:mid]
        node.children = node.children[:mid + 1]

        for child in new_node.children:
            child.parent = new_node

        # FIX: recompute subtree sizes for both halves
        node.subtree_size = sum(c.subtree_size for c in node.children)
        new_node.subtree_size = sum(c.subtree_size for c in new_node.children)

        self._insert_into_parent(node, promote_key, new_node)

    def _insert_into_parent(self, left, key, right):
        if left.parent is None:
            new_root = BPNode(is_leaf=False, order=self.order)
            self._node_count += 1
            new_root.keys = [key]
            new_root.children = [left, right]
            left.parent = new_root
            right.parent = new_root
            new_root.subtree_size = left.subtree_size + right.subtree_size
            self.root = new_root
            return

        parent = left.parent
        idx = parent.children.index(left)
        parent.keys.insert(idx, key)
        parent.children.insert(idx + 1, right)
        right.parent = parent

        if len(parent.keys) >= self.order:
            self._split_internal(parent)

    # ------------------------------------------------------------------ #
    #  Deletion                                                           #
    # ------------------------------------------------------------------ #

    def _remove_entry(self, score, member):
        key = (score, member)
        leaf = self._find_leaf(key)
        if key not in leaf.keys:
            return
        leaf.keys.remove(key)
        # FIX: update subtree sizes along the path to root
        node = leaf
        while node is not None:
            node.subtree_size -= 1
            node = node.parent
        min_keys = (self.order - 1) // 2
        if leaf is not self.root and len(leaf.keys) < min_keys:
            self._handle_underflow(leaf)

    def _handle_underflow(self, node):
        if node is self.root:
            if (
                not node.is_leaf
                and len(node.keys) == 0
                and len(node.children) == 1
            ):
                self.root = node.children[0]
                self.root.parent = None
                self._node_count -= 1
            return

        parent = node.parent
        idx = parent.children.index(node)

        if idx > 0:
            left_sib = parent.children[idx - 1]
            if len(left_sib.keys) > (self.order - 1) // 2:
                self._borrow_from_left(node, left_sib, parent, idx)
                return

        if idx < len(parent.children) - 1:
            right_sib = parent.children[idx + 1]
            if len(right_sib.keys) > (self.order - 1) // 2:
                self._borrow_from_right(node, right_sib, parent, idx)
                return

        if idx > 0:
            self._merge_nodes(parent.children[idx - 1], node, parent, idx - 1)
        else:
            self._merge_nodes(node, parent.children[idx + 1], parent, idx)

    def _borrow_from_left(self, node, left_sib, parent, idx):
        if node.is_leaf:
            borrowed = left_sib.keys.pop()
            node.keys.insert(0, borrowed)
            parent.keys[idx - 1] = node.keys[0]
            # FIX: adjust subtree sizes
            left_sib.subtree_size -= 1
            node.subtree_size += 1
        else:
            node.keys.insert(0, parent.keys[idx - 1])
            parent.keys[idx - 1] = left_sib.keys.pop()
            child = left_sib.children.pop()
            node.children.insert(0, child)
            child.parent = node
            moved = child.subtree_size
            left_sib.subtree_size -= moved
            node.subtree_size += moved

    def _borrow_from_right(self, node, right_sib, parent, idx):
        if node.is_leaf:
            borrowed = right_sib.keys.pop(0)
            node.keys.append(borrowed)
            parent.keys[idx] = right_sib.keys[0]
            right_sib.subtree_size -= 1
            node.subtree_size += 1
        else:
            node.keys.append(parent.keys[idx])
            parent.keys[idx] = right_sib.keys.pop(0)
            child = right_sib.children.pop(0)
            node.children.append(child)
            child.parent = node
            moved = child.subtree_size
            right_sib.subtree_size -= moved
            node.subtree_size += moved

    def _merge_nodes(self, left, right, parent, sep_idx):
        if left.is_leaf:
            left.keys.extend(right.keys)
            # FIX: update leaf chain to bypass the merged-away right node
            left.next_leaf = right.next_leaf
            if right.next_leaf is not None:
                right.next_leaf.prev_leaf = left
            left.subtree_size = len(left.keys)
        else:
            left.keys.append(parent.keys[sep_idx])
            left.keys.extend(right.keys)
            left.children.extend(right.children)
            for child in right.children:
                child.parent = left
            left.subtree_size = sum(c.subtree_size for c in left.children)

        parent.keys.pop(sep_idx)
        parent.children.remove(right)
        parent.subtree_size = sum(c.subtree_size for c in parent.children)
        self._node_count -= 1

        min_keys = (self.order - 1) // 2
        if parent is not self.root and len(parent.keys) < min_keys:
            self._handle_underflow(parent)
        elif parent is self.root and len(parent.keys) == 0:
            if len(parent.children) == 1:
                self.root = parent.children[0]
                self.root.parent = None
                self._node_count -= 1

    # ------------------------------------------------------------------ #
    #  Diagnostics                                                        #
    # ------------------------------------------------------------------ #

    def _leftmost_leaf(self):
        node = self.root
        while not node.is_leaf:
            node = node.children[0]
        return node
'''

with open("/app/bptree_zset.py", "w") as f:
    f.write(FIXED_CODE)
print("B+ tree sorted set fixed successfully.")
