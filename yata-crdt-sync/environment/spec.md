# YATA Sequence CRDT Specification

This document describes the YATA (Yet Another Transformation Approach) conflict-free replicated data type (CRDT) for collaborative text editing. Your task is to implement this specification as a Python module.

## 1. Data Model

### 1.1 Item ID (Lamport Timestamp)

Every item inserted into a YATA document is assigned a globally unique identifier consisting of:
- `client`: an integer identifying the client that created the item
- `clock`: a monotonically increasing integer per client, starting at 0

The pair `(client, clock)` uniquely identifies every item ever created. Clocks are incremented only by insertions, never by deletions.

### 1.2 Item

An Item represents a single character in the document. Each item has:

| Field | Type | Description |
|-------|------|-------------|
| `id` | ItemID | Unique identifier (client, clock) |
| `origin` | ItemID or None | ID of the left neighbor at creation time |
| `origin_right` | ItemID or None | ID of the right neighbor at creation time |
| `content` | str | Single character |
| `parent_key` | str | Name of the text type this item belongs to |
| `deleted` | bool | Whether this item has been tombstoned |
| `left` | Item or None | Current left neighbor in the linked list |
| `right` | Item or None | Current right neighbor in the linked list |

### 1.3 Document Structure

A YDoc maintains:
- A **client ID** (integer) identifying this replica
- A **clock** tracking the next available clock value for this client
- An **item map** for O(1) lookup of items by their (client, clock) ID
- A collection of **named text sequences** (YText), each maintaining its own doubly-linked list of Items
- A **delete set** recording which items have been deleted, stored as ranges per client

## 2. Operations

### 2.1 Local Insert

To insert a string at visible position `index` in a text sequence:

1. Walk the linked list from the start, counting non-deleted items. After counting `index` non-deleted items, the walk stops. Let `left` be the last item visited (or None if index is 0), and `right` be the current item (or None if at end).

2. For each character in the string:
   - Create a new Item with a fresh ID from this client's clock
   - Set `origin = left.id` (or None)
   - Set `origin_right = right.id` (or None), where `right` is the original right boundary (does not change across characters in the same insert call)
   - Link the item into the list between `left` and `right`
   - Update `left` to the newly inserted item for the next character

### 2.2 Local Delete

To delete `length` characters starting at visible position `index`:

1. Walk to the item at visible position `index` (counting non-deleted items)
2. Mark the next `length` non-deleted items as deleted
3. Add each deleted item's ID to the document's delete set

Deletions do NOT increment the client's clock.

### 2.3 Remote Integration (YATA Conflict Resolution)

When integrating a remotely-created item into the local document:

1. **Resolve references**: Look up `origin` and `origin_right` in the item map to find the actual Item objects. Set `left = find(origin)` and `right = find(origin_right)`.

2. **Check for conflicts**: A conflict exists if there are items between `left` and `right` that weren't there when the item was created. Specifically:
   - If `left` is None: conflict exists if `right` is None OR `right.left` is not None
   - If `left` is not None: conflict exists if `left.right` is not `right`

3. **Resolve conflicts** using the YATA algorithm:

   Initialize scanning from `o = left.right` (or `text._start` if `left` is None). Maintain two sets: `items_before_origin` and `conflicting`.

   For each item `o` encountered while `o` is not None and `o` is not `right`:
   - Add `o` to both `items_before_origin` and `conflicting`
   - **Case A** - Same origin (`o.origin == item.origin`):
     - If `o.id.client < item.id.client`: `o` goes to the left of the new item. Set `left = o` and clear `conflicting`.
     - Else if `item.origin_right == o.origin_right`: same conflict group boundary reached. Stop scanning.
     - Otherwise: continue scanning.
   - **Case B** - `o.origin` is not None and `find(o.origin)` is in `items_before_origin`:
     - If `find(o.origin)` is NOT in `conflicting`: `o` goes left. Set `left = o` and clear `conflicting`.
     - Otherwise: continue scanning.
   - **Case C** - Otherwise: stop scanning (break).

   After scanning, `left` holds the final insertion position.

4. **Link the item** into the list after `left`:
   - Set `item.left = left`
   - If `left` is not None: `item.right = left.right`, then `left.right = item`
   - If `left` is None: `item.right = text._start`, then `text._start = item`
   - If `item.right` is not None: `item.right.left = item`

5. **Add to item map** for future lookups.

## 3. State Vectors

A state vector is a dictionary mapping `client_id -> clock`, where `clock` is the next expected clock value (i.e., one past the maximum clock seen from that client).

The state vector summarizes which items a document has received from each client.

## 4. Delete Sets

A delete set records which items have been deleted, stored as a dictionary mapping `client_id -> list of (start_clock, length)` ranges. Ranges should be merged when adjacent or overlapping to keep the representation compact.

An item with ID `(client, clock)` is in the delete set if any range `(start, len)` for that client satisfies `start <= clock < start + len`.

## 5. Updates

An update is a JSON-serializable dictionary containing:

```python
{
    "items": [
        {
            "id": [client, clock],
            "origin": [client, clock] or None,
            "origin_right": [client, clock] or None,
            "content": "x",
            "parent_key": "text_name",
            "deleted": False
        },
        ...
    ],
    "delete_set": {
        client_id: [[start, length], ...],
        ...
    }
}
```

### 5.1 Encoding an Update

`encode_update(target_sv=None)`:
- If `target_sv` is None, treat it as `{}` (empty, meaning the target has nothing).
- For each item in the item map: include it if `item.id.clock >= target_sv.get(item.id.client, 0)`.
- Include the full delete set (delete sets are idempotent, so sending redundant entries is safe).
- Sort items by `(client, clock)` for deterministic ordering.

### 5.2 Applying an Update

`apply_update(update)`:
1. Sort items by `(client, clock)`.
2. For each item: skip if already in the item map. Check if dependencies are met (origin and origin_right can be found if not None). If dependencies are unmet, defer the item and retry after processing other items. Integrate using the YATA algorithm (Section 2.3).
3. Apply the delete set: for each range, mark matching items as deleted (if found and not already deleted).

Updates are **commutative** (order of application doesn't matter), **associative**, and **idempotent** (applying the same update twice is harmless).

## 6. Sync Protocol

Two documents synchronize using state vector exchange:

1. **Sync Step 1**: Client A sends its state vector to Client B.
2. **Sync Step 2**: Client B computes `encode_update(A_state_vector)` and sends the result to Client A. This contains only the items and deletions that A is missing.

For bidirectional sync, both clients perform both steps.

## 7. Snapshots

A snapshot captures a point-in-time view of the document as:

```python
{
    "state_vector": {client: clock, ...},
    "delete_set": {client: [[start, length], ...], ...}
}
```

To reconstruct the text at a snapshot:
1. Walk the linked list of the current document (which contains all items ever created).
2. For each item: include it in the output only if:
   - The item existed at snapshot time: `item.id.client` is in `snapshot.state_vector` AND `item.id.clock < snapshot.state_vector[item.id.client]`
   - The item was NOT deleted at snapshot time: the item's ID is NOT in `snapshot.delete_set`

This allows reconstructing any past document state without storing separate copies.

## 8. Required API

Your module `/app/crdt.py` must expose:

### YDoc(client_id: int)
- `get_text(name: str) -> YText` : Get or create a named text sequence
- `get_state_vector() -> dict[int, int]` : Return `{client: next_clock}`
- `encode_update(target_sv: dict | None = None) -> dict` : Encode state/diff as update
- `apply_update(update: dict) -> None` : Apply an update
- `snapshot() -> dict` : Create a snapshot of current state
- `text_at_snapshot(name: str, snap: dict) -> str` : Reconstruct text at snapshot

### YText
- `insert(index: int, text: str) -> None` : Insert text at visible position
- `delete(index: int, length: int) -> None` : Delete characters
- `to_string() -> str` : Get visible text (also via `__str__`)
- `__len__() -> int` : Count of visible characters
