# YATA Conflict Resolution Algorithm Reference

This document describes the internal data model and algorithms used by the Yjs
collaborative editing library. Your implementation must reproduce these semantics
exactly.

## Data Model

The CRDT represents a text document as a **doubly-linked list** of Item nodes in
document order. Each Item stores one character.

### Item Fields

| Field         | Type                     | Description |
|---------------|--------------------------|-------------|
| `id`          | `(clientID, clock)`      | Lamport-style unique identifier. Clock is per-client, increments by 1 for each character inserted. |
| `origin`      | `(clientID, clock)` or `None` | ID of the item immediately to the **left** at the time this character was inserted. `None` if inserted at document start. |
| `originRight` | `(clientID, clock)` or `None` | ID of the item immediately to the **right** at insertion time. `None` if inserted at document end. |
| `char`        | single character         | The content. |
| `deleted`     | boolean                  | Tombstone flag. Deleted items remain in the list but are not included in visible content. |
| `left`/`right`| Item or None             | Linked-list pointers in document order. |

### Struct Store

Items are also indexed in a **struct store**: a map from `clientID` to a list of
that client's Items **sorted by clock**. This enables O(log n) lookup by ID and
efficient state vector computation.

## Insertion

When a local client inserts text at visible position `index`:

1. Walk the linked list, counting only non-deleted items, to find the item at
   position `index - 1` (the **left neighbor**) and the item at position `index`
   (the **right neighbor**).
2. For each character in the text:
   - Create a new Item with `origin = left.id` (or `None`), `originRight = right.id`
     (or `None`), and a fresh `(clientID, clock)` identifier.
   - Splice it into the linked list between left and right.
   - Advance left to the newly inserted item; right stays the same.

## Deletion

Deletion is tombstone-based: mark the target items as `deleted = True`. They
remain in the linked list (so that origins remain resolvable) but are excluded
from visible content and index counting.

## Conflict Resolution (YATA Integration)

When a remote Item `I` arrives and needs to be inserted into the local list:

```
1. Find the local copy of I.origin (may be None). Set left = origin_item.
2. Set o = left.right (or list head if left is None).
3. Find the local copy of I.originRight. Call it origin_right_item.
4. Initialize: items_before_origin = {}, conflicting_items = {}.
5. While o is not None AND o is not origin_right_item:
     a. Add o to items_before_origin and conflicting_items.
     b. If o.origin == I.origin:                       [same insertion context]
          - If o.clientID < I.clientID:
              set left = o, reset conflicting_items.   [o wins left position]
          - Else if o.originRight == I.originRight:
              break.                                   [identical context; I goes first]
     c. Else if o.origin is not None:
          - Find o's origin item.
          - If o's origin is in items_before_origin:
              - If o's origin is NOT in conflicting_items:
                  set left = o, reset conflicting_items.
              - (Else: implicitly break)
          - Else: break.
     d. Else: break.
     e. Advance: o = o.right.
6. Splice I into the linked list after left.
7. Add I to the struct store.
```

**Key rule**: among concurrent inserts at the same position (same origin and
originRight), the item with the **lower clientID** is placed to the **left**
(earlier in document order).

## State Vector

A state vector is `{clientID: nextExpectedClock}`. For a client that has
inserted 5 characters (clocks 0 through 4), the entry is `{clientID: 5}`. An
empty document has an empty state vector.

## Sync Protocol

Two peers synchronize by exchanging state vectors and computing diffs:

1. Peer A sends its state vector to Peer B (and vice versa).
2. Each peer encodes an **update** containing all Items with
   `clock >= remote_sv[clientID]` for each client, plus a **delete set**
   listing all currently deleted item clocks.
3. Each peer applies the received update: integrate new Items using the YATA
   algorithm, then mark deletions from the delete set.

**Properties that must hold:**
- **Commutativity**: applying the same set of updates in any order yields
  identical content.
- **Idempotency**: re-applying an update already received is a no-op.
- **Convergence**: any two peers that have received the same set of updates
  produce identical visible content.

When integrating items from an update, some items may depend on others not yet
integrated (their origin or originRight hasn't been seen). Use a retry loop:
attempt to integrate each item; if its dependencies are missing, defer it.
Repeat until all items are integrated or no progress is made.

## Snapshots

A **snapshot** captures document state at a point in time as a pair:
- `state_vector`: identifies which Items existed at snapshot time
- `delete_set`: identifies which of those Items were deleted

**Restoring** a snapshot: walk the current linked list, include an Item's
character if `clock < sv[clientID]` AND `(clientID, clock)` is NOT in the
delete set.

## Delta Encoding

A **delta** between snapshots `old` and `new` contains:
- `structs`: Items present at `new` but not at `old`
  (those with `old_sv[client] <= clock < new_sv[client]`)
- `deletions`: Items deleted at `new` but not at `old`

Applying a delta: integrate the new Items, then apply the new deletions.
