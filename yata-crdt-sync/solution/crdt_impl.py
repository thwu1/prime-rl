"""Yjs V1 Binary Protocol Compatible CRDT Implementation.

Implements the YATA conflict resolution algorithm and Yjs V1 binary wire
format for cross-language interoperability with the real Yjs JavaScript library.
"""

from io import BytesIO
from collections import defaultdict

# ============================================================================
# Binary I/O primitives
# ============================================================================

def write_var_uint(buf, value):
    while value > 0x7F:
        buf.write(bytes([value & 0x7F | 0x80]))
        value >>= 7
    buf.write(bytes([value & 0x7F]))


def read_var_uint(buf):
    result = 0
    shift = 0
    while True:
        raw = buf.read(1)
        if not raw:
            raise ValueError("Unexpected end of buffer in read_var_uint")
        b = raw[0]
        result |= (b & 0x7F) << shift
        if b < 0x80:
            break
        shift += 7
    return result


def write_var_string(buf, s):
    encoded = s.encode('utf-8')
    write_var_uint(buf, len(encoded))
    buf.write(encoded)


def read_var_string(buf):
    length = read_var_uint(buf)
    data = buf.read(length)
    if len(data) < length:
        raise ValueError("Unexpected end of buffer in read_var_string")
    return data.decode('utf-8')


def write_uint8(buf, value):
    buf.write(bytes([value & 0xFF]))


def read_uint8(buf):
    raw = buf.read(1)
    if not raw:
        raise ValueError("Unexpected end of buffer in read_uint8")
    return raw[0]


# ============================================================================
# Data structures
# ============================================================================

class ItemID:
    __slots__ = ['client', 'clock']

    def __init__(self, client, clock):
        self.client = client
        self.clock = clock

    def __eq__(self, other):
        if not isinstance(other, ItemID):
            return NotImplemented
        return self.client == other.client and self.clock == other.clock

    def __hash__(self):
        return hash((self.client, self.clock))

    def __repr__(self):
        return f"ID({self.client},{self.clock})"


def compare_ids(a, b):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return a.client == b.client and a.clock == b.clock


class Item:
    __slots__ = ['id', 'origin', 'origin_right', 'content',
                 'parent_key', 'deleted', 'left', 'right']

    def __init__(self, item_id, origin, origin_right, content, parent_key,
                 deleted=False):
        self.id = item_id
        self.origin = origin          # ItemID or None
        self.origin_right = origin_right  # ItemID or None
        self.content = content        # single character (str len 1)
        self.parent_key = parent_key  # str or None
        self.deleted = deleted
        self.left = None
        self.right = None


class StructStore:
    def __init__(self):
        self.clients = {}  # client_id -> [Item, ...] sorted by clock

    def add(self, item):
        client = item.id.client
        if client not in self.clients:
            self.clients[client] = []
        items = self.clients[client]
        if not items or items[-1].id.clock < item.id.clock:
            items.append(item)
        else:
            lo, hi = 0, len(items)
            while lo < hi:
                mid = (lo + hi) // 2
                if items[mid].id.clock < item.id.clock:
                    lo = mid + 1
                else:
                    hi = mid
            if lo < len(items) and items[lo].id.clock == item.id.clock:
                return  # already present
            items.insert(lo, item)

    def get_item(self, item_id):
        items = self.clients.get(item_id.client)
        if not items:
            return None
        lo, hi = 0, len(items) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if items[mid].id.clock == item_id.clock:
                return items[mid]
            elif items[mid].id.clock < item_id.clock:
                lo = mid + 1
            else:
                hi = mid - 1
        return None

    def has_item(self, item_id):
        return self.get_item(item_id) is not None

    def get_clock(self, client):
        items = self.clients.get(client)
        if not items:
            return 0
        return items[-1].id.clock + 1

    def get_state_vector(self):
        sv = {}
        for client, items in self.clients.items():
            if items:
                sv[client] = items[-1].id.clock + 1
        return sv


# ============================================================================
# YText — linked-list text sequence
# ============================================================================

class YText:
    def __init__(self, doc, name):
        self.doc = doc
        self.name = name
        self._start = None
        self._length = 0

    def insert(self, index, text):
        left, right = self._find_position(index)
        orig_right_id = right.id if right else None
        for ch in text:
            item_id = ItemID(self.doc.client_id, self.doc.clock)
            self.doc.clock += 1
            origin = left.id if left else None
            item = Item(item_id, origin, orig_right_id, ch, self.name)
            # Use the actual linked-list neighbor (which may be a deleted item)
            # rather than the visible neighbor from _find_position, so that
            # deleted tombstones are not disconnected from the list.
            actual_right = left.right if left is not None else self._start
            item.left = left
            item.right = actual_right
            if left:
                left.right = item
            else:
                self._start = item
            if actual_right:
                actual_right.left = item
            self.doc.store.add(item)
            self._length += 1
            left = item

    def delete(self, index, length):
        item = self._start
        pos = 0
        while item:
            if not item.deleted:
                if pos == index:
                    break
                pos += 1
            item = item.right
        remaining = length
        while item and remaining > 0:
            if not item.deleted:
                item.deleted = True
                self.doc._add_to_delete_set(item.id.client, item.id.clock, 1)
                self._length -= 1
                remaining -= 1
            item = item.right

    def _find_position(self, index):
        left = None
        item = self._start
        pos = 0
        while item:
            if not item.deleted:
                if pos == index:
                    return left, item
                pos += 1
                left = item
            item = item.right
        return left, None

    def __str__(self):
        parts = []
        item = self._start
        while item:
            if not item.deleted:
                parts.append(item.content)
            item = item.right
        return ''.join(parts)

    def __len__(self):
        return self._length


# ============================================================================
# YDoc — CRDT document with binary V1 protocol support
# ============================================================================

class YDoc:
    def __init__(self, client_id):
        self.client_id = client_id
        self.clock = 0
        self.store = StructStore()
        self.texts = {}
        self._delete_ranges = defaultdict(list)

    def get_text(self, name):
        if name not in self.texts:
            self.texts[name] = YText(self, name)
        return self.texts[name]

    def get_state_vector(self):
        return self.store.get_state_vector()

    def _add_to_delete_set(self, client, clock, length):
        ranges = self._delete_ranges[client]
        ranges.append((clock, length))
        ranges.sort()
        merged = [ranges[0]]
        for s, l in ranges[1:]:
            ps, pl = merged[-1]
            if s <= ps + pl:
                merged[-1] = (ps, max(ps + pl, s + l) - ps)
            else:
                merged.append((s, l))
        self._delete_ranges[client] = merged

    def _compute_delete_set(self):
        ds = {}
        for client, items in self.store.clients.items():
            ranges = []
            for item in items:
                if item.deleted:
                    c = item.id.clock
                    if ranges and ranges[-1][0] + ranges[-1][1] == c:
                        ranges[-1] = (ranges[-1][0], ranges[-1][1] + 1)
                    else:
                        ranges.append((c, 1))
            if ranges:
                ds[client] = ranges
        return ds

    # ----------------------------------------------------------------
    # YATA conflict resolution
    # ----------------------------------------------------------------

    def _integrate_item(self, item):
        if self.store.has_item(item.id):
            return True

        # Resolve parent_key from origin chain
        if item.parent_key is None:
            if item.origin:
                oi = self.store.get_item(item.origin)
                if oi:
                    item.parent_key = oi.parent_key
            if item.parent_key is None and item.origin_right:
                ri = self.store.get_item(item.origin_right)
                if ri:
                    item.parent_key = ri.parent_key
            if item.parent_key is None:
                return False

        text = self.get_text(item.parent_key)

        # Resolve left/right from origin references
        left = None
        if item.origin is not None:
            left = self.store.get_item(item.origin)
            if left is None:
                return False

        right = None
        if item.origin_right is not None:
            right = self.store.get_item(item.origin_right)
            if right is None:
                return False

        # Check if conflict resolution is needed
        if left is None:
            needs_resolution = (right is None and text._start is not None) or \
                               (right is not None and right.left is not None)
        else:
            needs_resolution = left.right is not right

        if needs_resolution:
            o = left.right if left is not None else text._start
            items_before_origin = set()
            conflicting = set()

            while o is not None and o is not right:
                o_py_id = id(o)
                items_before_origin.add(o_py_id)
                conflicting.add(o_py_id)

                if compare_ids(item.origin, o.origin):
                    # Case A: same origin
                    if o.id.client < item.id.client:
                        left = o
                        conflicting.clear()
                    elif compare_ids(item.origin_right, o.origin_right):
                        break
                elif o.origin is not None:
                    o_origin_item = self.store.get_item(o.origin)
                    if o_origin_item is not None and \
                            id(o_origin_item) in items_before_origin:
                        if id(o_origin_item) not in conflicting:
                            left = o
                            conflicting.clear()
                    else:
                        break
                else:
                    break

                o = o.right

        # Link into the doubly-linked list
        item.left = left
        if left is not None:
            item.right = left.right
            left.right = item
        else:
            item.right = text._start
            text._start = item
        if item.right is not None:
            item.right.left = item

        self.store.add(item)
        if not item.deleted:
            text._length += 1
        return True

    def _integrate_items(self, pending):
        max_rounds = len(pending) + 1
        for _ in range(max_rounds):
            remaining = []
            for item in pending:
                if not self._integrate_item(item):
                    remaining.append(item)
            if not remaining:
                break
            if len(remaining) == len(pending):
                break
            pending = remaining

    # ----------------------------------------------------------------
    # Binary V1 decode
    # ----------------------------------------------------------------

    def apply_update_v1(self, data):
        buf = BytesIO(data)
        pending = []

        num_clients = read_var_uint(buf)
        for _ in range(num_clients):
            num_structs = read_var_uint(buf)
            client = read_var_uint(buf)
            clock = read_var_uint(buf)

            for _ in range(num_structs):
                info = read_uint8(buf)
                content_ref = info & 0x1F
                has_origin = bool(info & 0x80)
                has_right_origin = bool(info & 0x40)
                has_parent_sub = bool(info & 0x20)

                if content_ref == 0:  # GC
                    gc_len = read_var_uint(buf)
                    clock += gc_len
                    continue
                elif content_ref == 10:  # Skip
                    skip_len = read_var_uint(buf)
                    clock += skip_len
                    continue

                origin = None
                if has_origin:
                    origin = ItemID(read_var_uint(buf), read_var_uint(buf))

                right_origin = None
                if has_right_origin:
                    right_origin = ItemID(read_var_uint(buf),
                                         read_var_uint(buf))

                parent_key = None
                if not has_origin and not has_right_origin:
                    parent_is_key = read_var_uint(buf)
                    if parent_is_key:
                        parent_key = read_var_string(buf)
                    else:
                        read_var_uint(buf)  # parent client
                        read_var_uint(buf)  # parent clock
                    if has_parent_sub:
                        read_var_string(buf)  # parentSub

                if content_ref == 4:  # String content
                    content_str = read_var_string(buf)
                    for i, ch in enumerate(content_str):
                        iid = ItemID(client, clock + i)
                        io = origin if i == 0 else \
                            ItemID(client, clock + i - 1)
                        iro = right_origin
                        it = Item(iid, io, iro, ch, parent_key)
                        pending.append(it)
                    clock += len(content_str)

                elif content_ref == 1:  # Deleted content
                    del_len = read_var_uint(buf)
                    for i in range(del_len):
                        iid = ItemID(client, clock + i)
                        io = origin if i == 0 else \
                            ItemID(client, clock + i - 1)
                        iro = right_origin
                        it = Item(iid, io, iro, '\x00', parent_key,
                                  deleted=True)
                        pending.append(it)
                    clock += del_len

                elif content_ref == 2:  # JSON content
                    jlen = read_var_uint(buf)
                    for _ in range(jlen):
                        read_var_string(buf)
                    clock += jlen
                elif content_ref == 3:  # Binary content
                    blen = read_var_uint(buf)
                    buf.read(blen)
                    clock += 1
                elif content_ref == 5:  # Embed
                    read_var_string(buf)
                    clock += 1
                elif content_ref == 6:  # Format
                    read_var_string(buf)
                    read_var_string(buf)
                    clock += 1
                elif content_ref == 7:  # Type
                    read_var_uint(buf)
                    clock += 1

        # Read delete set
        ds_deletions = []
        ds_num_clients = read_var_uint(buf)
        for _ in range(ds_num_clients):
            ds_client = read_var_uint(buf)
            num_ranges = read_var_uint(buf)
            for _ in range(num_ranges):
                ds_clock = read_var_uint(buf)
                ds_length = read_var_uint(buf)
                ds_deletions.append((ds_client, ds_clock, ds_length))

        # Integrate pending items
        self._integrate_items(pending)

        # Apply delete set
        for ds_client, ds_clock, ds_length in ds_deletions:
            for c in range(ds_clock, ds_clock + ds_length):
                it = self.store.get_item(ItemID(ds_client, c))
                if it is not None and not it.deleted:
                    it.deleted = True
                    text = self.texts.get(it.parent_key)
                    if text:
                        text._length -= 1

    # ----------------------------------------------------------------
    # Binary V1 encode
    # ----------------------------------------------------------------

    def encode_state_as_update_v1(self, target_sv=None):
        if target_sv is None:
            target_sv = {}

        buf = BytesIO()

        # Determine which clients to write
        clients_to_write = {}
        for client, items in self.store.clients.items():
            if not items:
                continue
            store_clock = self.store.get_clock(client)
            target_clock = target_sv.get(client, 0)
            if store_clock > target_clock:
                clients_to_write[client] = target_clock

        # Write structs in descending client ID order
        write_var_uint(buf, len(clients_to_write))

        for client in sorted(clients_to_write.keys(), reverse=True):
            start_clock = clients_to_write[client]
            items = self.store.clients[client]
            filtered = [it for it in items if it.id.clock >= start_clock]
            if not filtered:
                continue

            groups = self._group_items_for_encoding(filtered)
            write_var_uint(buf, len(groups))
            write_var_uint(buf, client)
            write_var_uint(buf, filtered[0].id.clock)

            for group in groups:
                self._write_struct_group(buf, group)

        # Write delete set
        ds = self._compute_delete_set()
        write_var_uint(buf, len(ds))
        for client in sorted(ds.keys()):
            write_var_uint(buf, client)
            ranges = ds[client]
            write_var_uint(buf, len(ranges))
            for start, length in ranges:
                write_var_uint(buf, start)
                write_var_uint(buf, length)

        return buf.getvalue()

    def _group_items_for_encoding(self, items):
        if not items:
            return []
        groups = [[items[0]]]
        for item in items[1:]:
            prev = groups[-1][-1]
            first = groups[-1][0]
            can_merge = (
                item.id.client == prev.id.client and
                item.id.clock == prev.id.clock + 1 and
                item.deleted == prev.deleted and
                item.origin is not None and
                item.origin.client == prev.id.client and
                item.origin.clock == prev.id.clock and
                compare_ids(item.origin_right, first.origin_right) and
                item.parent_key == first.parent_key
            )
            if can_merge:
                groups[-1].append(item)
            else:
                groups.append([item])
        return groups

    def _write_struct_group(self, buf, group):
        first = group[0]
        is_deleted = first.deleted
        content_ref = 1 if is_deleted else 4

        has_origin = first.origin is not None
        has_right_origin = first.origin_right is not None

        info = (content_ref & 0x1F)
        if has_origin:
            info |= 0x80
        if has_right_origin:
            info |= 0x40

        write_uint8(buf, info)

        if has_origin:
            write_var_uint(buf, first.origin.client)
            write_var_uint(buf, first.origin.clock)

        if has_right_origin:
            write_var_uint(buf, first.origin_right.client)
            write_var_uint(buf, first.origin_right.clock)

        if not has_origin and not has_right_origin:
            write_var_uint(buf, 1)  # parentIsKey = 1
            write_var_string(buf, first.parent_key or '')

        if is_deleted:
            write_var_uint(buf, len(group))
        else:
            content = ''.join(it.content for it in group)
            write_var_string(buf, content)

    # ----------------------------------------------------------------
    # Snapshots
    # ----------------------------------------------------------------

    def snapshot(self):
        sv = self.store.get_state_vector()
        ds = self._compute_delete_set()
        return {'state_vector': dict(sv), 'delete_set': dict(ds)}

    def text_at_snapshot(self, name, snap):
        sv = snap['state_vector']
        ds = snap['delete_set']
        text = self.texts.get(name)
        if not text:
            return ''

        parts = []
        item = text._start
        while item:
            c = item.id.client
            clk = item.id.clock
            if c in sv and clk < sv[c]:
                deleted_at_snap = False
                for start, length in ds.get(c, []):
                    if start <= clk < start + length:
                        deleted_at_snap = True
                        break
                if not deleted_at_snap:
                    parts.append(item.content)
            item = item.right
        return ''.join(parts)
