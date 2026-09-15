
"""
YATA-based Sequence CRDT with temporal snapshot and delta encoding support.

Implements the YATA conflict resolution algorithm for concurrent inserts,
state-vector-based sync, and point-in-time snapshot reconstruction.
"""


class ItemID:
    """Lamport timestamp: (client_id, clock)."""
    __slots__ = ("client", "clock")

    def __init__(self, client, clock):
        self.client = client
        self.clock = clock

    def __eq__(self, other):
        return isinstance(other, ItemID) and self.client == other.client and self.clock == other.clock

    def __hash__(self):
        return hash((self.client, self.clock))

    def __repr__(self):
        return f"ID({self.client},{self.clock})"

    def to_tuple(self):
        return (self.client, self.clock)


class Item:
    """A single character node in the CRDT's doubly-linked list."""
    __slots__ = ("id", "origin", "origin_right", "char", "deleted", "left", "right")

    def __init__(self, item_id, origin, origin_right, char, deleted=False):
        self.id = item_id
        self.origin = origin          # ItemID or None
        self.origin_right = origin_right  # ItemID or None
        self.char = char              # single character
        self.deleted = deleted
        self.left = None
        self.right = None


class CRDTDoc:
    """YATA-based sequence CRDT with sync and temporal snapshot support."""

    def __init__(self, client_id):
        self.client_id = client_id
        self.clock = 0
        self._head = None            # head of the doubly-linked list
        self._store = {}             # {client_id: [Item, ...] sorted by clock}

    # ------------------------------------------------------------------
    # Item lookup
    # ------------------------------------------------------------------

    def _find_item(self, item_id):
        """Binary search for item by ID in the struct store."""
        if item_id is None:
            return None
        items = self._store.get(item_id.client)
        if items is None:
            return None
        lo, hi = 0, len(items) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            c = items[mid].id.clock
            if c == item_id.clock:
                return items[mid]
            elif c < item_id.clock:
                lo = mid + 1
            else:
                hi = mid - 1
        return None

    def _add_to_store(self, item):
        """Insert item into struct store maintaining clock order."""
        client = item.id.client
        if client not in self._store:
            self._store[client] = []
        items = self._store[client]
        lo, hi = 0, len(items)
        while lo < hi:
            mid = (lo + hi) // 2
            if items[mid].id.clock < item.id.clock:
                lo = mid + 1
            else:
                hi = mid
        items.insert(lo, item)

    # ------------------------------------------------------------------
    # Linked-list helpers
    # ------------------------------------------------------------------

    def _item_at_visible_index(self, index):
        """Walk the linked list and return the item at visible index."""
        pos = 0
        cur = self._head
        while cur is not None:
            if not cur.deleted:
                if pos == index:
                    return cur
                pos += 1
            cur = cur.right
        return None

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------

    def get_content(self):
        """Return visible (non-deleted) text."""
        parts = []
        cur = self._head
        while cur is not None:
            if not cur.deleted:
                parts.append(cur.char)
            cur = cur.right
        return "".join(parts)

    # ------------------------------------------------------------------
    # Insert
    # ------------------------------------------------------------------

    def insert(self, index, text):
        """Insert text at visible position index (one Item per character)."""
        for i, ch in enumerate(text):
            self._insert_char(index + i, ch)

    def _insert_char(self, index, ch):
        if index == 0:
            left = None
            right = self._head
        else:
            left = self._item_at_visible_index(index - 1)
            if left is None:
                raise IndexError(f"Insert index {index} out of range")
            right = left.right

        origin = left.id if left else None
        origin_right = right.id if right else None

        new_id = ItemID(self.client_id, self.clock)
        self.clock += 1

        new_item = Item(new_id, origin, origin_right, ch)
        new_item.left = left
        new_item.right = right

        if left is not None:
            left.right = new_item
        else:
            self._head = new_item
        if right is not None:
            right.left = new_item

        self._add_to_store(new_item)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, index, length=1):
        """Tombstone-delete `length` chars starting at visible index."""
        for _ in range(length):
            item = self._item_at_visible_index(index)
            if item is None:
                raise IndexError(f"Delete at index {index}: out of range")
            item.deleted = True

    # ------------------------------------------------------------------
    # State vector
    # ------------------------------------------------------------------

    def get_state_vector(self):
        """Return {client_id: next_expected_clock}."""
        sv = {}
        for client, items in self._store.items():
            if items:
                sv[client] = items[-1].id.clock + 1
        return sv

    # ------------------------------------------------------------------
    # Sync: encode / apply update
    # ------------------------------------------------------------------

    def encode_update(self, remote_sv=None):
        if remote_sv is None:
            remote_sv = {}

        structs = []
        delete_set = {}

        for client, items in self._store.items():
            start_clock = remote_sv.get(client, 0)
            deleted_clocks = []
            for item in items:
                if item.id.clock >= start_clock:
                    structs.append({
                        "id": item.id.to_tuple(),
                        "origin": item.origin.to_tuple() if item.origin else None,
                        "origin_right": item.origin_right.to_tuple() if item.origin_right else None,
                        "char": item.char,
                        "deleted": item.deleted,
                    })
                if item.deleted:
                    deleted_clocks.append(item.id.clock)
            if deleted_clocks:
                delete_set[client] = deleted_clocks

        return {"structs": structs, "delete_set": delete_set}

    def apply_update(self, update):
        structs = update.get("structs", [])
        delete_set = update.get("delete_set", {})

        # Integrate new items (retry loop for out-of-order deps)
        remaining = list(structs)
        safety = len(remaining) * len(remaining) + 1

        while remaining and safety > 0:
            safety -= 1
            next_round = []
            progress = False

            for s in remaining:
                item_id = ItemID(s["id"][0], s["id"][1])

                # Already integrated?
                if self._find_item(item_id) is not None:
                    progress = True
                    continue

                origin = ItemID(s["origin"][0], s["origin"][1]) if s["origin"] else None
                origin_right = ItemID(s["origin_right"][0], s["origin_right"][1]) if s["origin_right"] else None

                # Deps present?
                if origin is not None and self._find_item(origin) is None:
                    next_round.append(s)
                    continue
                if origin_right is not None and self._find_item(origin_right) is None:
                    next_round.append(s)
                    continue

                new_item = Item(item_id, origin, origin_right, s["char"], s["deleted"])
                self._integrate(new_item)
                progress = True

            if not progress:
                break
            remaining = next_round

        # Apply delete set
        for client_key, clocks in delete_set.items():
            client = int(client_key) if isinstance(client_key, str) else client_key
            for clock in clocks:
                item = self._find_item(ItemID(client, clock))
                if item is not None:
                    item.deleted = True

    # ------------------------------------------------------------------
    # YATA conflict resolution
    # ------------------------------------------------------------------

    def _integrate(self, new_item):
        """Insert a remote item using the YATA algorithm."""
        origin_item = self._find_item(new_item.origin)
        origin_right_item = self._find_item(new_item.origin_right)

        left = origin_item

        # First candidate: item right of origin
        if left is not None:
            o = left.right
        else:
            o = self._head

        items_before_origin = set()
        conflicting_items = set()

        while o is not None and o is not origin_right_item:
            items_before_origin.add(id(o))
            conflicting_items.add(id(o))

            if self._ids_eq(new_item.origin, o.origin):
                # Case 1: same origin
                if o.id.client < new_item.id.client:
                    left = o
                    conflicting_items = set()
                elif self._ids_eq(new_item.origin_right, o.origin_right):
                    # Identical context — new item goes first (left of o)
                    break
                # else: continue scanning
            elif o.origin is not None:
                o_origin_item = self._find_item(o.origin)
                if o_origin_item is not None and id(o_origin_item) in items_before_origin:
                    # Case 2: o's origin is among scanned items
                    if id(o_origin_item) not in conflicting_items:
                        left = o
                        conflicting_items = set()
                    # else: break — new item goes before o
                else:
                    break
            else:
                break

            o = o.right

        # Splice into linked list after `left`
        new_item.left = left
        if left is not None:
            new_item.right = left.right
            left.right = new_item
        else:
            new_item.right = self._head
            self._head = new_item
        if new_item.right is not None:
            new_item.right.left = new_item

        self._add_to_store(new_item)

    @staticmethod
    def _ids_eq(a, b):
        if a is None and b is None:
            return True
        if a is None or b is None:
            return False
        return a.client == b.client and a.clock == b.clock

    # ------------------------------------------------------------------
    # Merge (bidirectional sync)
    # ------------------------------------------------------------------

    def merge(self, other):
        sv_self = self.get_state_vector()
        sv_other = other.get_state_vector()
        u_self = self.encode_update(sv_other)
        u_other = other.encode_update(sv_self)
        self.apply_update(u_other)
        other.apply_update(u_self)

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def snapshot(self):
        sv = self.get_state_vector()
        ds = {}
        for client, items in self._store.items():
            deleted = [item.id.clock for item in items if item.deleted]
            if deleted:
                ds[client] = deleted
        return {"state_vector": sv, "delete_set": ds}

    def restore_snapshot(self, snap):
        sv = snap["state_vector"]
        ds = snap["delete_set"]

        deleted_set = set()
        for client_key, clocks in ds.items():
            c = int(client_key) if isinstance(client_key, str) else client_key
            for clock in clocks:
                deleted_set.add((c, clock))

        parts = []
        cur = self._head
        while cur is not None:
            c, k = cur.id.client, cur.id.clock
            if k < sv.get(c, 0) and (c, k) not in deleted_set:
                parts.append(cur.char)
            cur = cur.right
        return "".join(parts)

    # ------------------------------------------------------------------
    # Delta encoding
    # ------------------------------------------------------------------

    def encode_delta(self, old_snap, new_snap):
        old_sv = old_snap["state_vector"]
        new_sv = new_snap["state_vector"]
        old_ds = old_snap["delete_set"]
        new_ds = new_snap["delete_set"]

        structs = []
        for client, items in self._store.items():
            lo = old_sv.get(client, 0)
            hi = new_sv.get(client, 0)
            for item in items:
                if lo <= item.id.clock < hi:
                    structs.append({
                        "id": item.id.to_tuple(),
                        "origin": item.origin.to_tuple() if item.origin else None,
                        "origin_right": item.origin_right.to_tuple() if item.origin_right else None,
                        "char": item.char,
                        "deleted": item.deleted,
                    })

        # Compute newly-deleted items
        old_deleted = set()
        for client_key, clocks in old_ds.items():
            c = int(client_key) if isinstance(client_key, str) else client_key
            for clock in clocks:
                old_deleted.add((c, clock))

        deletions = []
        for client_key, clocks in new_ds.items():
            c = int(client_key) if isinstance(client_key, str) else client_key
            for clock in clocks:
                if (c, clock) not in old_deleted:
                    deletions.append((c, clock))

        return {
            "structs": structs,
            "deletions": deletions,
            "base_sv": old_sv,
            "target_sv": new_sv,
        }

    def apply_delta(self, delta):
        self.apply_update({"structs": delta["structs"], "delete_set": {}})
        for client, clock in delta["deletions"]:
            item = self._find_item(ItemID(client, clock))
            if item is not None:
                item.deleted = True
