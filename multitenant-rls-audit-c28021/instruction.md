A multi-tenant document management system uses PostgreSQL Row Level Security for access control. The database simulates a Supabase-like auth architecture with `auth.uid()` and `auth.jwt()` helper functions, and the roles `anon`, `authenticated`, and `service_role`.

The schema is in `/app/schema.sql` (read-only). RLS policies, helper functions, and views are in `/app/policies.sql`. A security audit has identified multiple vulnerabilities. Fix all issues in `/app/policies.sql` so the system passes verification.

Run `/app/setup.sh` to initialize the database after making changes.

**Security invariants that must hold:**

- Authorization decisions must rely only on server-controlled claims and verified table data. Client-modifiable JWT fields must never be used to grant resource access.

- Documents with `confidential` classification must only be accessible to their creator and users with an explicit share entry. Organization membership alone must not grant access to confidential documents.

- Views that expose RLS-protected tables must enforce the same row-level restrictions as direct queries against the underlying tables.

- Privileged helper functions must be hardened against schema-based privilege escalation attacks.

- Creating a document share requires the sharer to have prior access to that document — as the creator or through a write-permission share. The enforcement must work without causing circular policy dependencies.

- The audit log must be append-only for non-superuser roles.

- Every policy scoped to logged-in users must not be evaluable by anonymous sessions.

- All `auth.uid()` and `auth.jwt()` references in policy definitions must avoid redundant per-row evaluation.

**Verification**: Tests start PostgreSQL, load both SQL files, seed test data, and assert each invariant. Tests verify both that attacks are blocked and that legitimate operations succeed — including org members viewing non-confidential documents, creators accessing their own confidential documents, and write-share holders re-sharing.
