The PostgreSQL database `appdb` (user `postgres`, no password, local trust auth) implements custom trigger-based referential integrity across `departments` -> `projects` -> `tasks` (plus `_cascade_log`). Start PostgreSQL with `pg_ctlcluster $(ls /etc/postgresql/ | sort -V | tail -1) main start`.

Two PL/pgSQL trigger functions -- `cascade_fk_update()` and `cascade_fk_delete()` -- dynamically construct and execute SQL for cascade operations. They support composite multi-column foreign keys with variable column counts determined at runtime from trigger arguments. A helper function `needs_quoting()` makes type-based decisions about SQL value quoting for dynamic query construction.

The system contains multiple interacting classes of security and correctness vulnerabilities in its dynamic SQL construction, value quoting approach, NULL handling semantics, and security configuration. The vulnerability classes interact through shared code paths -- a surface-level fix addressing only one class leaves the system exploitable through others.

The database environment also contains DDL-level infrastructure that silently interferes with certain function property modifications. The `_cascade_log` table may not accurately reflect actual cascade activity for all operation types. Any fix that does not account for and neutralize these environmental factors will appear to succeed but fail under verification.

Analyze the complete trigger infrastructure and broader database environment, then produce:

- `/app/vulnerability_analysis.sql` -- SQL demonstrating at least three distinct exploitation or failure vectors against the unfixed system, including at least one involving environmental interference with fix attempts
- `/app/fixed_functions.sql` -- corrected definitions eliminating every vulnerability class while preserving correct cascade behavior for composite keys, special characters, and NULL-valued key columns
- Apply all corrections to the running database, ensuring fixes are durable and not silently reverted or degraded by other database objects