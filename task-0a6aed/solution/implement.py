#!/usr/bin/env python3

"""
Build and write a complete rank-augmented B+ tree sorted set implementation
to /app/sorted_set.py, and a complete RESP server to /app/server.py, then
validate both against Redis and internal checks.
"""

import os
import sys
import textwrap


def build_sorted_set_source() -> str:
    """Construct the full sorted_set.py source as a string."""

    parts = []

    # -- Module docstring and imports --
    parts.append(textwrap.dedent('''\

        """
        Rank-augmented B+ tree sorted set implementation.
        """

        from __future__ import annotations

        import bisect
        from typing import List, Optional, Tuple

        from interface import SortedSetInterface
    '''))

    # -- Node class --
    parts.append(textwrap.dedent('''\

        class _Node:
            """Single node in the B+ tree (leaf or internal)."""

            __slots__ = ("leaf", "keys", "children", "counts", "next_leaf")

            def __init__(self, leaf: bool = True):
                self.leaf = leaf
                self.keys: list = []
                self.children: list = []
                self.counts: list = []  # counts[i] = total elements in children[i] subtree
                self.next_leaf: Optional[_Node] = None
    '''))

    # -- BPTree class --
    parts.append(textwrap.dedent('''\

        class _BPTree:
            """Rank-augmented B+ tree with configurable max_keys."""

            def __init__(self, max_keys: int = 24):
                assert max_keys >= 8
                self.max_keys = max_keys
                self.min_keys = max_keys // 2
                self.root = _Node(leaf=True)
                self._size = 0
                self._height = 1
                self._node_count = 1

            @property
            def size(self) -> int:
                return self._size

            def _leftmost_leaf(self) -> _Node:
                n = self.root
                while not n.leaf:
                    n = n.children[0]
                return n

            # -- insert --

            def insert(self, key) -> bool:
                path: list[tuple[_Node, int]] = []
                node = self.root
                while not node.leaf:
                    idx = bisect.bisect_right(node.keys, key)
                    path.append((node, idx))
                    node = node.children[idx]

                pos = bisect.bisect_left(node.keys, key)
                if pos < len(node.keys) and node.keys[pos] == key:
                    return False

                node.keys.insert(pos, key)
                self._size += 1

                for anc, ci in path:
                    anc.counts[ci] += 1

                if len(node.keys) > self.max_keys:
                    self._split(node, path)

                return True

            def _split(self, node: _Node, path: list[tuple[_Node, int]]) -> None:
                mid = len(node.keys) // 2
                right = _Node(leaf=node.leaf)
                self._node_count += 1

                if node.leaf:
                    right.keys = node.keys[mid:]
                    node.keys = node.keys[:mid]
                    right.next_leaf = node.next_leaf
                    node.next_leaf = right
                    sep = right.keys[0]
                else:
                    sep = node.keys[mid]
                    right.keys = node.keys[mid + 1:]
                    right.children = node.children[mid + 1:]
                    right.counts = node.counts[mid + 1:]
                    node.keys = node.keys[:mid]
                    node.children = node.children[:mid + 1]
                    node.counts = node.counts[:mid + 1]

                if not path:
                    new_root = _Node(leaf=False)
                    self._node_count += 1
                    new_root.keys = [sep]
                    new_root.children = [node, right]
                    new_root.counts = [
                        len(node.keys) if node.leaf else sum(node.counts),
                        len(right.keys) if right.leaf else sum(right.counts),
                    ]
                    self.root = new_root
                    self._height += 1
                else:
                    parent, ci = path[-1]
                    parent.keys.insert(ci, sep)
                    parent.children.insert(ci + 1, right)
                    lc = len(node.keys) if node.leaf else sum(node.counts)
                    rc = len(right.keys) if right.leaf else sum(right.counts)
                    parent.counts[ci] = lc
                    parent.counts.insert(ci + 1, rc)

                    if len(parent.keys) > self.max_keys:
                        self._split(parent, path[:-1])

            # -- delete --

            def delete(self, key) -> bool:
                path: list[tuple[_Node, int]] = []
                node = self.root
                while not node.leaf:
                    idx = bisect.bisect_right(node.keys, key)
                    path.append((node, idx))
                    node = node.children[idx]

                pos = bisect.bisect_left(node.keys, key)
                if pos >= len(node.keys) or node.keys[pos] != key:
                    return False

                node.keys.pop(pos)
                self._size -= 1

                for anc, ci in path:
                    anc.counts[ci] -= 1

                if path and len(node.keys) < self.min_keys:
                    self._fix_underflow(node, path)

                while not self.root.leaf and len(self.root.children) == 1:
                    self.root = self.root.children[0]
                    self._height -= 1
                    self._node_count -= 1

                return True

            def _fix_underflow(self, node: _Node, path: list[tuple[_Node, int]]) -> None:
                parent, ci = path[-1]

                # try borrow from left sibling
                if ci > 0:
                    left = parent.children[ci - 1]
                    if len(left.keys) > self.min_keys:
                        if node.leaf:
                            node.keys.insert(0, left.keys.pop())
                            parent.keys[ci - 1] = node.keys[0]
                            parent.counts[ci - 1] -= 1
                            parent.counts[ci] += 1
                        else:
                            node.keys.insert(0, parent.keys[ci - 1])
                            parent.keys[ci - 1] = left.keys.pop()
                            ch = left.children.pop()
                            cnt = left.counts.pop()
                            node.children.insert(0, ch)
                            node.counts.insert(0, cnt)
                            parent.counts[ci - 1] -= cnt
                            parent.counts[ci] += cnt
                        return

                # try borrow from right sibling
                if ci < len(parent.children) - 1:
                    right = parent.children[ci + 1]
                    if len(right.keys) > self.min_keys:
                        if node.leaf:
                            node.keys.append(right.keys.pop(0))
                            parent.keys[ci] = right.keys[0]
                            parent.counts[ci] += 1
                            parent.counts[ci + 1] -= 1
                        else:
                            node.keys.append(parent.keys[ci])
                            parent.keys[ci] = right.keys.pop(0)
                            ch = right.children.pop(0)
                            cnt = right.counts.pop(0)
                            node.children.append(ch)
                            node.counts.append(cnt)
                            parent.counts[ci] += cnt
                            parent.counts[ci + 1] -= cnt
                        return

                # merge
                if ci > 0:
                    left = parent.children[ci - 1]
                    if not node.leaf:
                        left.keys.append(parent.keys.pop(ci - 1))
                        left.keys.extend(node.keys)
                        left.children.extend(node.children)
                        left.counts.extend(node.counts)
                    else:
                        parent.keys.pop(ci - 1)
                        left.keys.extend(node.keys)
                        left.next_leaf = node.next_leaf
                    parent.children.pop(ci)
                    mc = parent.counts.pop(ci)
                    parent.counts[ci - 1] += mc
                    self._node_count -= 1
                else:
                    right = parent.children[ci + 1]
                    if not node.leaf:
                        node.keys.append(parent.keys.pop(ci))
                        node.keys.extend(right.keys)
                        node.children.extend(right.children)
                        node.counts.extend(right.counts)
                    else:
                        parent.keys.pop(ci)
                        node.keys.extend(right.keys)
                        node.next_leaf = right.next_leaf
                    parent.children.pop(ci + 1)
                    mc = parent.counts.pop(ci + 1)
                    parent.counts[ci] += mc
                    self._node_count -= 1

                if len(path) > 1 and len(parent.keys) < self.min_keys:
                    self._fix_underflow(parent, path[:-1])

            # -- rank operations --

            def get_rank(self, key) -> Optional[int]:
                node = self.root
                rank = 0

                while not node.leaf:
                    idx = bisect.bisect_right(node.keys, key)
                    for i in range(idx):
                        rank += node.counts[i]
                    node = node.children[idx]

                pos = bisect.bisect_left(node.keys, key)
                if pos >= len(node.keys) or node.keys[pos] != key:
                    return None
                return rank + pos

            def from_rank(self, rank: int):
                if rank < 0 or rank >= self._size:
                    return None
                node = self.root
                rem = rank
                while not node.leaf:
                    for i, c in enumerate(node.counts):
                        if rem < c:
                            node = node.children[i]
                            break
                        rem -= c
                    else:
                        return None
                if rem < len(node.keys):
                    return node.keys[rem]
                return None

            # -- range helpers --

            def range_by_rank(self, start: int, end: int) -> list:
                if self._size == 0 or start > end or start >= self._size:
                    return []
                start = max(0, start)
                end = min(end, self._size - 1)

                first_key = self.from_rank(start)
                if first_key is None:
                    return []

                node = self.root
                while not node.leaf:
                    idx = bisect.bisect_right(node.keys, first_key)
                    node = node.children[idx]
                pos = bisect.bisect_left(node.keys, first_key)

                result = []
                need = end - start + 1
                while need > 0 and node is not None:
                    while pos < len(node.keys) and need > 0:
                        result.append(node.keys[pos])
                        pos += 1
                        need -= 1
                    node = node.next_leaf
                    pos = 0
                return result

            def find_ge(self, key) -> Optional[Tuple[_Node, int]]:
                if self._size == 0:
                    return None
                node = self.root
                while not node.leaf:
                    idx = bisect.bisect_right(node.keys, key)
                    node = node.children[idx]
                pos = bisect.bisect_left(node.keys, key)
                while pos >= len(node.keys):
                    node = node.next_leaf
                    if node is None:
                        return None
                    pos = 0
                return (node, pos)
    '''))

    # -- SortedSet wrapper --
    parts.append(textwrap.dedent('''\

        class BPTreeSortedSet(SortedSetInterface):
            """Redis-like sorted set backed by a rank-augmented B+ tree."""

            def __init__(self, max_keys: int = 24):
                self._tree = _BPTree(max_keys=max_keys)
                self._members: dict[str, float] = {}

            @staticmethod
            def _fmt(items: list, withscores: bool) -> list:
                if withscores:
                    return [(m, s) for s, m in items]
                return [m for _s, m in items]

            def zadd(
                self,
                items: List[Tuple[float, str]],
                nx: bool = False,
                xx: bool = False,
                gt: bool = False,
                lt: bool = False,
                ch: bool = False,
            ) -> int:
                added = 0
                changed = 0

                for score, member in items:
                    if member in self._members:
                        if nx:
                            continue
                        old = self._members[member]
                        if gt and score <= old:
                            continue
                        if lt and score >= old:
                            continue
                        if old != score:
                            self._tree.delete((old, member))
                            self._tree.insert((score, member))
                            self._members[member] = score
                            changed += 1
                    else:
                        if xx:
                            continue
                        self._tree.insert((score, member))
                        self._members[member] = score
                        added += 1

                return (added + changed) if ch else added

            def zincrby(self, member: str, increment: float) -> float:
                if member in self._members:
                    old = self._members[member]
                    new = old + increment
                    self._tree.delete((old, member))
                    self._tree.insert((new, member))
                    self._members[member] = new
                    return new
                self._tree.insert((increment, member))
                self._members[member] = increment
                return increment

            def zrem(self, *members: str) -> int:
                removed = 0
                for m in members:
                    if m in self._members:
                        s = self._members.pop(m)
                        self._tree.delete((s, m))
                        removed += 1
                return removed

            def zscore(self, member: str) -> Optional[float]:
                return self._members.get(member)

            def zcard(self) -> int:
                return len(self._members)

            def zrank(self, member: str) -> Optional[int]:
                if member not in self._members:
                    return None
                return self._tree.get_rank((self._members[member], member))

            def zrevrank(self, member: str) -> Optional[int]:
                r = self.zrank(member)
                if r is None:
                    return None
                return len(self._members) - 1 - r

            def zrange(
                self,
                start: int,
                stop: int,
                reverse: bool = False,
                withscores: bool = True,
            ) -> list:
                n = len(self._members)
                if n == 0:
                    return []
                if start < 0:
                    start += n
                if stop < 0:
                    stop += n
                start = max(0, start)
                stop = min(n - 1, stop)
                if start > stop:
                    return []

                if reverse:
                    rs = n - 1 - stop
                    re = n - 1 - start
                    items = self._tree.range_by_rank(rs, re)
                    items = list(reversed(items))
                else:
                    items = self._tree.range_by_rank(start, stop)

                return self._fmt(items, withscores)

            def zrangebyscore(
                self,
                min_score: float,
                max_score: float,
                min_exclusive: bool = False,
                max_exclusive: bool = False,
                offset: int = 0,
                count: int = -1,
                withscores: bool = True,
            ) -> list:
                if self._tree.size == 0:
                    return []

                pos_info = self._tree.find_ge((min_score, ""))
                if pos_info is None:
                    return []

                leaf, pos = pos_info
                results: list = []
                skipped = 0
                collected = 0

                while leaf is not None:
                    while pos < len(leaf.keys):
                        sc, mb = leaf.keys[pos]
                        if sc < min_score or (min_exclusive and sc == min_score):
                            pos += 1
                            continue
                        if sc > max_score or (max_exclusive and sc == max_score):
                            return self._fmt(results, withscores)
                        if skipped < offset:
                            skipped += 1
                            pos += 1
                            continue
                        results.append((sc, mb))
                        collected += 1
                        if count >= 0 and collected >= count:
                            return self._fmt(results, withscores)
                        pos += 1
                    leaf = leaf.next_leaf
                    pos = 0

                return self._fmt(results, withscores)

            def zcount(
                self,
                min_score: float,
                max_score: float,
                min_exclusive: bool = False,
                max_exclusive: bool = False,
            ) -> int:
                return len(
                    self.zrangebyscore(
                        min_score, max_score,
                        min_exclusive, max_exclusive,
                        withscores=False,
                    )
                )

            def zpopmin(self, count: int = 1) -> List[Tuple[str, float]]:
                result: list[tuple[str, float]] = []
                for _ in range(min(count, len(self._members))):
                    key = self._tree.from_rank(0)
                    if key is None:
                        break
                    sc, mb = key
                    self._tree.delete(key)
                    del self._members[mb]
                    result.append((mb, sc))
                return result

            def zpopmax(self, count: int = 1) -> List[Tuple[str, float]]:
                result: list[tuple[str, float]] = []
                for _ in range(min(count, len(self._members))):
                    key = self._tree.from_rank(self._tree.size - 1)
                    if key is None:
                        break
                    sc, mb = key
                    self._tree.delete(key)
                    del self._members[mb]
                    result.append((mb, sc))
                return result

            def _get_tree_info(self) -> dict:
                return {
                    "height": self._tree._height,
                    "node_count": self._tree._node_count,
                    "max_keys_per_node": self._tree.max_keys,
                    "total_elements": self._tree._size,
                }

            def _verify_integrity(self) -> bool:
                tree = self._tree

                def _check(node: _Node, is_root: bool) -> tuple[bool, int, set[int]]:
                    if not is_root and len(node.keys) < tree.min_keys:
                        return False, 0, set()
                    if len(node.keys) > tree.max_keys:
                        return False, 0, set()
                    for i in range(len(node.keys) - 1):
                        if node.keys[i] >= node.keys[i + 1]:
                            return False, 0, set()

                    if node.leaf:
                        return True, len(node.keys), {0}

                    if len(node.children) != len(node.keys) + 1:
                        return False, 0, set()
                    if len(node.counts) != len(node.children):
                        return False, 0, set()

                    total = 0
                    depths: set[int] = set()
                    for i, child in enumerate(node.children):
                        ok, cnt, ds = _check(child, False)
                        if not ok:
                            return False, 0, set()
                        if node.counts[i] != cnt:
                            return False, 0, set()
                        total += cnt
                        depths |= {d + 1 for d in ds}

                    if len(depths) > 1:
                        return False, 0, set()
                    return True, total, depths

                ok, count, _ = _check(tree.root, True)
                if not ok or count != tree._size or count != len(self._members):
                    return False

                leaf = tree._leftmost_leaf()
                prev = None
                lcount = 0
                while leaf is not None:
                    for k in leaf.keys:
                        if prev is not None and k <= prev:
                            return False
                        prev = k
                        lcount += 1
                    leaf = leaf.next_leaf

                return lcount == count
    '''))

    return "\n".join(parts)


def build_server_source() -> str:
    """Construct the complete server.py with command dispatch."""

    return textwrap.dedent('''\
        """
        RESP2 protocol server for sorted set operations — complete implementation.

        """

        import socket
        import sys
        import threading

        sys.path.insert(0, "/app")


        class RESPParser:
            def __init__(self, sock):
                self._file = sock.makefile("rb")

            def read_command(self):
                try:
                    line = self._file.readline()
                    if not line:
                        return None
                    line = line.strip()
                    if not line:
                        return None
                    if line.startswith(b"*"):
                        count = int(line[1:])
                        if count < 0:
                            return None
                        args = []
                        for _ in range(count):
                            header = self._file.readline().strip()
                            if header.startswith(b"$"):
                                length = int(header[1:])
                                if length < 0:
                                    args.append(None)
                                else:
                                    data = self._file.read(length + 2)[:length]
                                    args.append(data.decode("utf-8", errors="replace"))
                            else:
                                args.append(header.decode("utf-8", errors="replace"))
                        return args
                    else:
                        parts = line.decode("utf-8", errors="replace").split()
                        return parts if parts else None
                except (ConnectionError, OSError, ValueError):
                    return None

            def close(self):
                try:
                    self._file.close()
                except Exception:
                    pass


        def resp_ok():
            return b"+OK\\r\\n"

        def resp_pong():
            return b"+PONG\\r\\n"

        def resp_error(msg):
            return f"-ERR {msg}\\r\\n".encode()

        def resp_integer(n):
            return f":{n}\\r\\n".encode()

        def resp_bulk(s):
            if s is None:
                return b"$-1\\r\\n"
            encoded = str(s).encode()
            return b"$" + str(len(encoded)).encode() + b"\\r\\n" + encoded + b"\\r\\n"

        def resp_array(items):
            if items is None:
                return b"*-1\\r\\n"
            return b"*" + str(len(items)).encode() + b"\\r\\n" + b"".join(items)

        def resp_empty_array():
            return b"*0\\r\\n"


        def _format_score(score):
            """Format a float score the way Redis does."""
            if score == int(score):
                return str(int(score))
            return f"{score:g}"


        def _parse_score_bound(s):
            """Parse a ZRANGEBYSCORE bound.  Returns (value, exclusive)."""
            if s.startswith("("):
                return float(s[1:]), True
            return float(s), False


        class SortedSetServer:
            def __init__(self, host="0.0.0.0", port=6380):
                self.host = host
                self.port = port
                self.stores = {}
                self._lock = threading.Lock()
                self._running = False

            def _get_store(self, key):
                with self._lock:
                    if key not in self.stores:
                        from sorted_set import BPTreeSortedSet
                        self.stores[key] = BPTreeSortedSet()
                    return self.stores[key]

            def _delete_store(self, key):
                with self._lock:
                    return self.stores.pop(key, None) is not None

            def command_dispatch(self, args):
                if not args:
                    return resp_error("empty command")

                cmd = args[0].upper()

                # -- meta commands --
                if cmd == "PING":
                    return resp_pong()
                if cmd == "COMMAND":
                    return resp_empty_array()
                if cmd == "SELECT":
                    return resp_ok()
                if cmd == "CONFIG":
                    if len(args) >= 2 and args[1].upper() == "SET":
                        return resp_ok()
                    return resp_empty_array()
                if cmd == "DBSIZE":
                    return resp_integer(len(self.stores))
                if cmd in ("FLUSHALL", "FLUSHDB"):
                    with self._lock:
                        self.stores.clear()
                    return resp_ok()
                if cmd == "DEL":
                    cnt = 0
                    for k in args[1:]:
                        if self._delete_store(k):
                            cnt += 1
                    return resp_integer(cnt)

                if len(args) < 2:
                    return resp_error(f"wrong number of arguments for '{cmd}'")

                key = args[1]
                ss = self._get_store(key)

                # -- ZADD --
                if cmd == "ZADD":
                    nx = xx = gt = lt = ch = False
                    i = 2
                    while i < len(args):
                        flag = args[i].upper()
                        if flag == "NX":
                            nx = True; i += 1
                        elif flag == "XX":
                            xx = True; i += 1
                        elif flag == "GT":
                            gt = True; i += 1
                        elif flag == "LT":
                            lt = True; i += 1
                        elif flag == "CH":
                            ch = True; i += 1
                        else:
                            break
                    items = []
                    while i + 1 < len(args):
                        score = float(args[i])
                        member = args[i + 1]
                        items.append((score, member))
                        i += 2
                    result = ss.zadd(items, nx=nx, xx=xx, gt=gt, lt=lt, ch=ch)
                    return resp_integer(result)

                # -- ZREM --
                if cmd == "ZREM":
                    result = ss.zrem(*args[2:])
                    return resp_integer(result)

                # -- ZSCORE --
                if cmd == "ZSCORE":
                    score = ss.zscore(args[2])
                    if score is None:
                        return resp_bulk(None)
                    return resp_bulk(_format_score(score))

                # -- ZCARD --
                if cmd == "ZCARD":
                    return resp_integer(ss.zcard())

                # -- ZRANK --
                if cmd == "ZRANK":
                    rank = ss.zrank(args[2])
                    if rank is None:
                        return resp_bulk(None)
                    return resp_integer(rank)

                # -- ZREVRANK --
                if cmd == "ZREVRANK":
                    rank = ss.zrevrank(args[2])
                    if rank is None:
                        return resp_bulk(None)
                    return resp_integer(rank)

                # -- ZRANGE --
                if cmd == "ZRANGE":
                    start_val = int(args[2])
                    stop_val = int(args[3])
                    withscores = False
                    reverse = False
                    for a in args[4:]:
                        au = a.upper()
                        if au == "WITHSCORES":
                            withscores = True
                        elif au == "REV":
                            reverse = True
                    result = ss.zrange(start_val, stop_val, reverse=reverse, withscores=withscores)
                    if withscores:
                        parts = []
                        for member, score in result:
                            parts.append(resp_bulk(member))
                            parts.append(resp_bulk(_format_score(score)))
                        return resp_array(parts)
                    else:
                        return resp_array([resp_bulk(m) for m in result])

                # -- ZREVRANGE --
                if cmd == "ZREVRANGE":
                    start_val = int(args[2])
                    stop_val = int(args[3])
                    withscores = "WITHSCORES" in [a.upper() for a in args[4:]]
                    result = ss.zrange(start_val, stop_val, reverse=True, withscores=withscores)
                    if withscores:
                        parts = []
                        for member, score in result:
                            parts.append(resp_bulk(member))
                            parts.append(resp_bulk(_format_score(score)))
                        return resp_array(parts)
                    else:
                        return resp_array([resp_bulk(m) for m in result])

                # -- ZRANGEBYSCORE --
                if cmd == "ZRANGEBYSCORE":
                    min_val, min_excl = _parse_score_bound(args[2])
                    max_val, max_excl = _parse_score_bound(args[3])
                    withscores = False
                    offset = 0
                    count = -1
                    i = 4
                    while i < len(args):
                        au = args[i].upper()
                        if au == "WITHSCORES":
                            withscores = True
                            i += 1
                        elif au == "LIMIT":
                            offset = int(args[i + 1])
                            count = int(args[i + 2])
                            i += 3
                        else:
                            i += 1
                    result = ss.zrangebyscore(
                        min_val, max_val,
                        min_exclusive=min_excl, max_exclusive=max_excl,
                        offset=offset, count=count,
                        withscores=withscores,
                    )
                    if withscores:
                        parts = []
                        for member, score in result:
                            parts.append(resp_bulk(member))
                            parts.append(resp_bulk(_format_score(score)))
                        return resp_array(parts)
                    else:
                        return resp_array([resp_bulk(m) for m in result])

                # -- ZCOUNT --
                if cmd == "ZCOUNT":
                    min_val, min_excl = _parse_score_bound(args[2])
                    max_val, max_excl = _parse_score_bound(args[3])
                    result = ss.zcount(min_val, max_val, min_exclusive=min_excl, max_exclusive=max_excl)
                    return resp_integer(result)

                # -- ZPOPMIN --
                if cmd == "ZPOPMIN":
                    cnt = int(args[2]) if len(args) > 2 else 1
                    result = ss.zpopmin(cnt)
                    parts = []
                    for member, score in result:
                        parts.append(resp_bulk(member))
                        parts.append(resp_bulk(_format_score(score)))
                    return resp_array(parts)

                # -- ZPOPMAX --
                if cmd == "ZPOPMAX":
                    cnt = int(args[2]) if len(args) > 2 else 1
                    result = ss.zpopmax(cnt)
                    parts = []
                    for member, score in result:
                        parts.append(resp_bulk(member))
                        parts.append(resp_bulk(_format_score(score)))
                    return resp_array(parts)

                # -- ZINCRBY --
                if cmd == "ZINCRBY":
                    increment = float(args[2])
                    member = args[3]
                    new_score = ss.zincrby(member, increment)
                    return resp_bulk(_format_score(new_score))

                return resp_error(f"unknown command '{cmd}'")

            def _handle_client(self, conn, addr):
                parser = RESPParser(conn)
                try:
                    while self._running:
                        args = parser.read_command()
                        if args is None:
                            break
                        try:
                            response = self.command_dispatch(args)
                            conn.sendall(response)
                        except Exception as exc:
                            conn.sendall(resp_error(str(exc)))
                except (ConnectionError, BrokenPipeError, OSError):
                    pass
                finally:
                    parser.close()
                    conn.close()

            def run(self):
                self._running = True
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self._sock.bind((self.host, self.port))
                self._sock.listen(128)
                self._sock.settimeout(1.0)

                print(f"Sorted-set server listening on {self.host}:{self.port}", flush=True)

                while self._running:
                    try:
                        conn, addr = self._sock.accept()
                        t = threading.Thread(
                            target=self._handle_client, args=(conn, addr), daemon=True
                        )
                        t.start()
                    except socket.timeout:
                        continue
                    except OSError:
                        break

                self._sock.close()

            def stop(self):
                self._running = False


        if __name__ == "__main__":
            port = int(sys.argv[1]) if len(sys.argv) > 1 else 6380
            server = SortedSetServer(port=port)
            try:
                server.run()
            except KeyboardInterrupt:
                server.stop()
    ''')


def validate_sorted_set():
    """Quick sanity checks on the sorted set implementation."""
    sys.path.insert(0, "/app")

    if "sorted_set" in sys.modules:
        del sys.modules["sorted_set"]

    from sorted_set import BPTreeSortedSet

    # Test 1: Basic insert/delete with leaf chain integrity
    ss = BPTreeSortedSet()
    for i in range(500):
        ss.zadd([(float(i), f"m{i:04d}")])
    for i in range(200):
        ss.zrem(f"m{i:04d}")

    elems = ss.zrangebyscore(float("-inf"), float("inf"))
    assert len(elems) == 300, f"Range scan: {len(elems)} != 300"
    assert len(set(m for m, _ in elems)) == 300, "Duplicates in range scan"
    assert ss._verify_integrity(), "Integrity check failed"

    # Test 2: ZPOPMAX returns descending order
    ss2 = BPTreeSortedSet()
    for i in range(10):
        ss2.zadd([(float(i), f"e{i}")])
    r = ss2.zpopmax(3)
    assert r == [("e9", 9.0), ("e8", 8.0), ("e7", 7.0)], f"ZPOPMAX order: {r}"

    # Test 3: LIMIT offset correct
    r2 = ss2.zrangebyscore(0.0, 9.0, offset=2, count=3)
    assert r2 == [("e2", 2.0), ("e3", 3.0), ("e4", 4.0)], f"LIMIT offset: {r2}"

    # Test 4: Cross-validate range scan vs rank access
    ss3 = BPTreeSortedSet()
    import random
    rng = random.Random(42)
    for i in range(2000):
        ss3.zadd([(round(rng.uniform(-50, 50), 2), f"v{i}")])

    by_score = ss3.zrangebyscore(float("-inf"), float("inf"))
    by_rank = ss3.zrange(0, -1)
    assert by_score == by_rank, "Range scan / rank access mismatch"

    # Test 5: Rank accuracy
    ref = {}
    ss4 = BPTreeSortedSet()
    for i in range(1000):
        score = round(rng.uniform(-100, 100), 2)
        ss4.zadd([(score, f"r{i}")])
        ref[f"r{i}"] = score

    sorted_ref = sorted(ref.items(), key=lambda x: (x[1], x[0]))
    for i, (member, _) in enumerate(sorted_ref):
        assert ss4.zrank(member) == i, f"Rank mismatch for {member}"

    print("Sorted set sanity checks passed.")


def validate_server():
    """Start server and validate with redis-py + redis-cli."""
    import subprocess
    import time

    # Start the custom server
    proc = subprocess.Popen(
        [sys.executable, "/app/server.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        import redis
        r = redis.Redis(port=6380, decode_responses=True)
        for _ in range(50):
            try:
                r.ping()
                break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("Server did not start")

        # Basic ZADD + ZRANGE
        r.delete("stest")
        r.zadd("stest", {"c": 3.0, "a": 1.0, "b": 2.0})
        result = r.zrange("stest", 0, -1, withscores=True)
        assert result == [("a", 1.0), ("b", 2.0), ("c", 3.0)], f"ZRANGE: {result}"

        # Cross-validate with Redis
        ref = redis.Redis(port=6379, decode_responses=True)
        ref.delete("stest")
        ref.zadd("stest", {"c": 3.0, "a": 1.0, "b": 2.0})
        ref_result = ref.zrange("stest", 0, -1, withscores=True)
        assert result == ref_result, f"Cross-val mismatch: {result} vs {ref_result}"

        # redis-cli test
        cli_result = subprocess.run(
            ["redis-cli", "-p", "6380", "ZADD", "clitest", "1.0", "hello"],
            capture_output=True, text=True, timeout=10,
        )
        assert cli_result.returncode == 0

        r.close()
        ref.close()
        print("Server validation passed.")
    finally:
        proc.terminate()
        proc.wait(timeout=5)


if __name__ == "__main__":
    # Generate sorted_set.py
    ss_source = build_sorted_set_source()
    with open("/app/sorted_set.py", "w") as f:
        f.write(ss_source)
    print(f"Wrote /app/sorted_set.py ({len(ss_source)} bytes)")

    # Generate server.py
    srv_source = build_server_source()
    with open("/app/server.py", "w") as f:
        f.write(srv_source)
    print(f"Wrote /app/server.py ({len(srv_source)} bytes)")

    validate_sorted_set()
    validate_server()
