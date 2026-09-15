A FHIR CDS Hooks 2.0 medication safety service is deployed at `/app/` behind an nginx reverse proxy (port 9000 → Flask on port 5000) with PostgreSQL audit logging. A clinical informatics compliance review has identified specification violations and logic defects across the deployed code and configuration. PostgreSQL and nginx are installed but not running; the audit database has not been initialized.

The deployed system consists of `/app/server.py`, `/app/interaction_engine.py`, an nginx site configuration, and clinical knowledge base files at `/app/data/`. Diagnose all issues and bring the deployment into full compliance.

The fully compliant system must satisfy:

**nginx reverse proxy** (port 9000 → 5000): CORS headers (`Access-Control-Allow-Origin: *`, `Access-Control-Allow-Methods: GET, POST, OPTIONS`, `Access-Control-Allow-Headers: Content-Type, Authorization`) on all responses. HTTP 204 for OPTIONS preflight requests. `X-CDS-Service-Version: 2.0` header on every response. Client request body limit of 2MB.

**Audit trail** (`cds_audit.decision_log`): each medication-safety POST inserts one row with `patient_id`, `hook_instance`, `cards_count`, `max_severity` (highest-severity card or `none`), and `request_hash` (SHA-256 hex digest of raw request body).

**CDS Hooks discovery** (`GET /cds-services`): conformant service descriptor with proper CDS Hooks prefetch token templates requesting Patient, active MedicationRequest (`status=active`), and AllergyIntolerance resources.

**Interaction detection**: drug-drug interactions detected symmetrically regardless of draft/active ordering. Allergy cross-reactivity alerts when an ordered drug is cross-reactive with documented allergens per the group definitions in the knowledge base. Cards ordered by severity (critical first).

**Card structure**: `summary` (string), `detail` (string), `indicator` (`critical`|`warning`|`info`), `source` (object with `label` string).