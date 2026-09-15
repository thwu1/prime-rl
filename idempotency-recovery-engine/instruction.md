A ride-hailing service uses `/app/idempotency.py` as its idempotency processing engine for ride requests backed by PostgreSQL. The system was recently deployed but is experiencing critical data integrity failures in production:

- After a server crash mid-request, retrying the same idempotency key causes database errors instead of resuming gracefully
- Other reliability and correctness issues have been reported but not yet fully characterized

PostgreSQL 16 is installed but not running. Start it with `pg_ctlcluster 16 main start`. The `idempotency` database is pre-created with the schema from `/app/schema.sql`. Connection parameters are in `/app/config.py`.

The database schema encodes the intended system design — study its constraints, indexes, and foreign key relationships carefully. Diagnose and fix all bugs in `/app/idempotency.py`.