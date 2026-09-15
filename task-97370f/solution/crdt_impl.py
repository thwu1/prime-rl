#!/usr/bin/env python3
"""
YATA Sequence CRDT Engine

Implements the YATA conflict resolution algorithm for concurrent text editing
with guaranteed convergence, state vector-based sync, and snapshot temporal queries.

"""

from collections import defaultdict


class ID:
    """Lamport timestamp identifier for CRDT items."""
    __slots__ = ('client', 'clock')

    def __init__(self, client, clock):
        self.client = client
        self.clock = clock

    def __eq__(self, other):
        if not isinstance(other, ID):
            return NotImplemented
        return self.client == other.client and self.clock == other.clock

    def __hash__(self):
        return hash((self.client, self.clock))

    def __repr__(self):
        return f"ID({self.client},{self.clock})"

    def to_tuple(self):
        return (self.client, self.clock)

    @staticmethod
    def from_tuple(t):
        if t is None:
            return None
        return ID(t[0], t[1])


def _ids_equal(a, b):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return a.client == b.client and a.clock == b.clock


class Item:
    """An item in the CRDT sequence (compound representation — may hold multiple chars)."""
    __slots__ = ('id', 'origin', 'origin_right', 'content', 'length',
                 'deleted', 'left', 'right')

    def __init__(self, id, origin, origin_right, content, deleted=False):
        self.id = id
        self.origin = origin
        self.origin_right = origin_right
        self.content = content
        self.length = len(content) if content else 0
        self.deleted = deleted
        self.left = None
        self.right = None

    @property
    def last_id(self):
        if self.length <= 1:
            return self.id
        return ID(self.id.client, self.id.clock + self.length - 1)

    def __repr__(self):
        d = " DEL" if self.deleted else ""
        return f"Item({self.id},'{self.content}'{d})"


class Document:
    """
    YATA sequence CRDT document.

    Supports concurrent editing by multiple clients with guaranteed convergence,
    state-vector-based synchronization, and snapshot-based temporal queries.
    """

    def __init__(self, client_id):
        self.client_id = client_id
        self.clock = 0
        self._start = None
        self._client_items = {}   # client_id -> list[Item] sorted by clock
        self._delete_set = {}     # client_id(int) -> list[(clock, length)]

    # ------------------------------------------------------------------ index

    def _register(self, item):
        cid = item.id.client
        if cid not in self._client_items:
            self._client_items[cid] = []
        lst = self._client_items[cid]
        lo, hi = 0, len(lst)
        while lo < hi:
            mid = (lo + hi) // 2
            if lst[mid].id.clock < item.id.clock:
                lo = mid + 1
            else:
                hi = mid
        lst.insert(lo, item)

    def _find_containing(self, id_val):
        """Find item whose clock range contains id_val.clock. No split."""
        if id_val is None:
            return None
        cid = id_val.client
        items = self._client_items.get(cid)
        if items is None:
            return None
        lo, hi = 0, len(items)
        while lo < hi:
            mid = (lo + hi) // 2
            item = items[mid]
            if item.id.clock + item.length <= id_val.clock:
                lo = mid + 1
            elif item.id.clock > id_val.clock:
                hi = mid
            else:
                return item
        return None

    def _get_clock(self, cid):
        items = self._client_items.get(cid)
        if not items:
            return 0
        expected = 0
        for item in items:
            if item.id.clock != expected:
                break
            expected = item.id.clock + item.length
        return expected

    # --------------------------------------------------------------- splitting

    def _split(self, item, offset):
        assert 0 < offset < item.length
        right = Item(
            id=ID(item.id.client, item.id.clock + offset),
            origin=ID(item.id.client, item.id.clock + offset - 1),
            origin_right=item.origin_right,
            content=item.content[offset:],
            deleted=item.deleted,
        )
        right.left = item
        right.right = item.right
        if item.right is not None:
            item.right.left = right
        item.right = right
        item.content = item.content[:offset]
        item.length = offset
        self._register(right)
        return item, right

    def _get_clean_end(self, id_val):
        """Return item ending at exactly id_val.clock. Splits if needed."""
        if id_val is None:
            return None
        item = self._find_containing(id_val)
        if item is None:
            return None
        end = item.id.clock + item.length - 1
        if end == id_val.clock:
            return item
        off = id_val.clock - item.id.clock + 1
        left, _ = self._split(item, off)
        return left

    def _get_clean_start(self, id_val):
        """Return item starting at exactly id_val.clock. Splits if needed."""
        if id_val is None:
            return None
        item = self._find_containing(id_val)
        if item is None:
            return None
        if item.id.clock == id_val.clock:
            return item
        off = id_val.clock - item.id.clock
        _, right = self._split(item, off)
        return right

    # -------------------------------------------------------- YATA integration

    def _integrate(self, new_item):
        # Resolve origin -> left
        if new_item.origin is not None:
            left = self._get_clean_end(new_item.origin)
        else:
            left = None

        # Resolve originRight -> right boundary
        if new_item.origin_right is not None:
            right = self._get_clean_start(new_item.origin_right)
        else:
            right = None

        # Scan start
        if left is not None:
            o = left.right
        else:
            o = self._start

        # YATA conflict resolution — two-set algorithm
        items_before_origin = set()
        conflicting_items = set()

        while o is not None and o is not right:
            items_before_origin.add(id(o))
            conflicting_items.add(id(o))

            if _ids_equal(new_item.origin, o.origin):
                # Case 1 — same origin
                if o.id.client < new_item.id.client:
                    left = o
                    conflicting_items = set()
                elif _ids_equal(new_item.origin_right, o.origin_right):
                    break
                # else keep scanning
            else:
                if o.origin is not None:
                    o_origin_item = self._find_containing(o.origin)
                    if o_origin_item is not None and id(o_origin_item) in items_before_origin:
                        # Case 2 — o's origin was seen earlier in the conflict zone
                        if id(o_origin_item) not in conflicting_items:
                            left = o
                            conflicting_items = set()
                        # else o is part of current conflict group
                    else:
                        break
                else:
                    break
            o = o.right

        # Insert after left
        new_item.left = left
        if left is not None:
            new_item.right = left.right
            left.right = new_item
        else:
            new_item.right = self._start
            self._start = new_item
        if new_item.right is not None:
            new_item.right.left = new_item

        self._register(new_item)

        # Check stored delete_set — mark deleted if needed
        if not new_item.deleted:
            cid = new_item.id.client
            if cid in self._delete_set:
                istart = new_item.id.clock
                iend = istart + new_item.length
                for dc, dl in self._delete_set[cid]:
                    os = max(dc, istart)
                    oe = min(dc + dl, iend)
                    if os < oe:
                        self._mark_deleted_range(cid, os, oe - os)
                        break

    # -------------------------------------------------------------- public API

    def _find_left_neighbor(self, pos):
        if pos <= 0:
            return None
        curr = self._start
        visible = 0
        while curr is not None:
            if not curr.deleted:
                end_vis = visible + curr.length
                if end_vis >= pos:
                    offset = pos - visible
                    if 0 < offset < curr.length:
                        left, _ = self._split(curr, offset)
                        return left
                    return curr
                visible = end_vis
            curr = curr.right
        # pos beyond end — last visible item
        last = None
        curr = self._start
        while curr is not None:
            if not curr.deleted:
                last = curr
            curr = curr.right
        return last

    def insert(self, pos, text):
        if not text:
            return
        left = self._find_left_neighbor(pos)

        right_visible = None
        scan = left.right if left is not None else self._start
        while scan is not None:
            if not scan.deleted:
                right_visible = scan
                break
            scan = scan.right

        origin = left.last_id if left is not None else None
        origin_right = right_visible.id if right_visible is not None else None

        new_item = Item(
            id=ID(self.client_id, self.clock),
            origin=origin,
            origin_right=origin_right,
            content=text,
        )
        self.clock += len(text)
        self._integrate(new_item)

    def delete(self, pos, length):
        remaining = length
        while remaining > 0:
            curr = self._start
            visible = 0
            target = None
            while curr is not None:
                if not curr.deleted:
                    if visible + curr.length > pos:
                        target = curr
                        break
                    visible += curr.length
                curr = curr.right
            if target is None:
                break
            offset = pos - visible
            if offset > 0:
                _, target = self._split(target, offset)
            to_del = min(remaining, target.length)
            if to_del < target.length:
                self._split(target, to_del)
            target.deleted = True
            cid = target.id.client
            if cid not in self._delete_set:
                self._delete_set[cid] = []
            self._delete_set[cid].append((target.id.clock, target.length))
            remaining -= to_del

    def get_text(self):
        parts = []
        curr = self._start
        while curr is not None:
            if not curr.deleted:
                parts.append(curr.content)
            curr = curr.right
        return ''.join(parts)

    # ----------------------------------------------------------- state vector

    def get_state_vector(self):
        sv = {}
        for cid in self._client_items:
            c = self._get_clock(cid)
            if c > 0:
                sv[cid] = c
        return sv

    # ------------------------------------------------------------------- sync

    def encode_update(self, target_sv=None):
        if target_sv is None:
            target_sv = {}
        items_data = []
        seen = set()
        curr = self._start
        while curr is not None:
            cid = curr.id.client
            min_clock = target_sv.get(cid, 0)
            key = (cid, curr.id.clock)
            if key not in seen and curr.id.clock + curr.length > min_clock:
                seen.add(key)
                items_data.append({
                    'id': [cid, curr.id.clock],
                    'origin': curr.origin.to_tuple() if curr.origin else None,
                    'origin_right': curr.origin_right.to_tuple() if curr.origin_right else None,
                    'content': curr.content,
                    'deleted': curr.deleted,
                })
            curr = curr.right
        ds = {}
        for cid, ranges in self._delete_set.items():
            ds[cid] = list(ranges)
        return {'items': items_data, 'delete_set': ds}

    def apply_update(self, update):
        items_data = update.get('items', [])
        sorted_items = sorted(items_data, key=lambda x: (x['id'][0], x['id'][1]))

        remaining = list(sorted_items)
        for _ in range(len(sorted_items) + 1):
            if not remaining:
                break
            nxt = []
            progress = False
            for item_data in remaining:
                cid, clock = item_data['id']
                content = item_data['content']
                item_len = len(content)
                our_clock = self._get_clock(cid)

                if clock + item_len <= our_clock:
                    if item_data.get('deleted', False):
                        self._mark_deleted_range(cid, clock, item_len)
                    progress = True
                    continue

                offset = max(0, our_clock - clock)
                if offset > 0:
                    actual_clock = clock + offset
                    actual_content = content[offset:]
                    actual_origin = (cid, actual_clock - 1)
                else:
                    actual_clock = clock
                    actual_content = content
                    actual_origin = item_data.get('origin')

                origin = ID.from_tuple(actual_origin) if actual_origin else None
                origin_right = ID.from_tuple(item_data.get('origin_right'))

                deps_ok = True
                if origin and not self._find_containing(origin):
                    deps_ok = False
                if origin_right and not self._find_containing(origin_right):
                    deps_ok = False

                if not deps_ok:
                    nxt.append(item_data)
                    continue

                new_item = Item(
                    id=ID(cid, actual_clock),
                    origin=origin,
                    origin_right=origin_right,
                    content=actual_content,
                    deleted=item_data.get('deleted', False),
                )
                self._integrate(new_item)
                progress = True

            if not progress:
                break
            remaining = nxt

        for cid_key, ranges in update.get('delete_set', {}).items():
            cid = int(cid_key) if isinstance(cid_key, str) else cid_key
            if cid not in self._delete_set:
                self._delete_set[cid] = []
            for clock, length in ranges:
                self._delete_set[cid].append((clock, length))
                self._mark_deleted_range(cid, clock, length)

    def _mark_deleted_range(self, cid, start_clock, length):
        end_clock = start_clock + length
        c = start_clock
        while c < end_clock:
            item = self._find_containing(ID(cid, c))
            if item is None:
                c += 1
                continue
            if item.deleted:
                c = item.id.clock + item.length
                continue
            off = c - item.id.clock
            if off > 0:
                _, item = self._split(item, off)
            rem = end_clock - item.id.clock
            if rem < item.length:
                self._split(item, rem)
            item.deleted = True
            c = item.id.clock + item.length

    # --------------------------------------------------------------- snapshot

    def snapshot(self):
        sv = self.get_state_vector()
        ds = {}
        for cid, ranges in self._delete_set.items():
            ds[cid] = list(ranges)
        return {'state_vector': sv, 'delete_set': ds}

    def text_at_snapshot(self, snap):
        sv = snap['state_vector']
        ds_raw = snap['delete_set']
        deleted = set()
        for cid_key, ranges in ds_raw.items():
            cid = int(cid_key) if isinstance(cid_key, str) else cid_key
            for clock, length in ranges:
                for i in range(length):
                    deleted.add((cid, clock + i))
        parts = []
        curr = self._start
        while curr is not None:
            cid = curr.id.client
            max_clock = sv.get(cid, 0)
            for i in range(curr.length):
                clock = curr.id.clock + i
                if clock >= max_clock:
                    break
                if (cid, clock) not in deleted:
                    parts.append(curr.content[i])
            curr = curr.right
        return ''.join(parts)
