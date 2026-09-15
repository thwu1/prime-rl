A multi-warehouse inventory reservation system backed by PostgreSQL has concurrency defects in its stored procedures at `/app/procedures.sql`. The database schema at `/app/schema.sql` defines tables and constraints and must not be altered.

Six PL/pgSQL functions manage product stock across warehouses. Each call executes as its own transaction (autocommit connections). Under concurrent load, the system exhibits deadlocks, data corruption, and invariant violations. Fix all defects so the system operates correctly under arbitrary concurrency.

**`reserve_order_stock(p_order_id INT) -> BOOLEAN`** — Atomically reserve inventory for all lines of a PENDING order. Sets status to RESERVED on success.

**`cancel_order(p_order_id INT) -> BOOLEAN`** — Cancel a RESERVED order: release every active reservation, mark each reservation record RELEASED, set order status to CANCELLED.

**`fulfill_order(p_order_id INT) -> BOOLEAN`** — Ship a RESERVED order: decrement `quantity_on_hand` and `quantity_reserved` per active reservation, mark each reservation FULFILLED, set order status to SHIPPED.

**`transfer_stock(p_product_id, p_from_warehouse_id, p_to_warehouse_id, p_quantity) -> BOOLEAN`** — Move unreserved stock between warehouses. Must verify sufficient unreserved stock atomically.

**`reallocate_reservation(p_order_id, p_product_id, p_from_warehouse_id, p_to_warehouse_id) -> BOOLEAN`** — Move an existing active reservation to a different warehouse without moving physical stock. Must update the reservation record so downstream operations target the correct location.

**`batch_reserve_orders(p_order_ids INT[]) -> TABLE(order_id INT, success BOOLEAN, error_msg TEXT)`** — Best-effort batch reservation: attempt to reserve each order in the array. Each order independently succeeds (status becomes RESERVED) or fails (status becomes FAILED) without affecting others. Returns one row per input order indicating outcome. Must not deadlock when concurrent batch calls reference overlapping products across warehouses. Within a single batch, earlier orders' successful reservations must reduce availability for later orders.

**Invariants** (schema-enforced; procedures must never violate):
- `quantity_on_hand >= 0`, `quantity_reserved >= 0`, `quantity_reserved <= quantity_on_hand`
- `quantity_reserved` equals the aggregate of ACTIVE reservation quantities per inventory row
- No ACTIVE reservations remain for CANCELLED or FAILED orders; all reservations FULFILLED for SHIPPED orders
- Stock conserved during transfers; reallocations preserve per-row reservation consistency
- When two operations race on the same order, exactly one succeeds; the other receives a clean status rejection, never a constraint violation

**Files**:
- `/app/schema.sql` — read-only table definitions
- `/app/procedures.sql` — stored procedures to fix

**Verification**: `bash /tests/test.sh`
