"""
Security verification tests for multi-tenant RLS policies.

"""

import pytest
import psycopg2
import psycopg2.errors
import json
import uuid
import subprocess
import time
import re

DB_NAME = "multitenant_test"

# Fixed UUIDs for reproducibility
ALICE_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
BOB_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
EVE_ID = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
ORG_A_ID = "00000001-0001-0001-0001-000000000001"
ORG_B_ID = "00000002-0002-0002-0002-000000000002"
PROJECT_A_ID = "11111111-1111-1111-1111-111111111111"
DOC_A_ID = "dddddddd-dddd-dddd-dddd-ddddddddddda"
DOC_B_ID = "dddddddd-dddd-dddd-dddd-dddddddddddb"
AUDIT_ENTRY_ID = "ffffffff-ffff-ffff-ffff-ffffffffffff"


def get_conn():
    """Get a new autocommit connection to the test database."""
    conn = psycopg2.connect(dbname=DB_NAME, user="postgres")
    conn.autocommit = True
    return conn


def authenticate_as(cur, user_id, app_metadata=None, user_metadata=None):
    """Switch session to authenticated role with given user identity."""
    claims = json.dumps({
        "sub": str(user_id),
        "role": "authenticated",
        "app_metadata": app_metadata or {},
        "user_metadata": user_metadata or {},
    })
    cur.execute("SELECT set_config('request.jwt.claim.sub', %s, false)", (str(user_id),))
    cur.execute("SELECT set_config('request.jwt.claims', %s, false)", (claims,))
    cur.execute("SET ROLE authenticated")


def switch_to_anon(cur):
    """Switch session to anon role."""
    cur.execute("RESET ROLE")
    cur.execute("SELECT set_config('request.jwt.claim.sub', '', false)")
    cur.execute("SELECT set_config('request.jwt.claims', '{}', false)")
    cur.execute("SET ROLE anon")


def reset(cur):
    """Reset to superuser role."""
    cur.execute("RESET ROLE")
    cur.execute("SELECT set_config('request.jwt.claim.sub', '', false)")
    cur.execute("SELECT set_config('request.jwt.claims', '{}', false)")


def setup_module(module):
    """Initialize PostgreSQL and set up test database with seed data."""
    subprocess.run(["service", "postgresql", "start"], capture_output=True)
    for _ in range(30):
        result = subprocess.run(["pg_isready"], capture_output=True)
        if result.returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError("PostgreSQL did not become ready")

    # Create fresh test database
    conn = psycopg2.connect(dbname="postgres", user="postgres")
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {DB_NAME}")
        cur.execute(f"CREATE DATABASE {DB_NAME}")
    conn.close()

    # Load schema and policies
    conn = psycopg2.connect(dbname=DB_NAME, user="postgres")
    conn.autocommit = True
    with conn.cursor() as cur:
        with open("/app/schema.sql") as f:
            cur.execute(f.read())
        with open("/app/policies.sql") as f:
            cur.execute(f.read())

        # Seed test users
        cur.execute(
            "INSERT INTO auth.users (id, email, raw_app_meta_data, raw_user_meta_data) VALUES "
            "(%s, 'alice@example.com', %s, '{}'),"
            "(%s, 'bob@example.com', %s, '{}'),"
            "(%s, 'eve@example.com', '{}', %s)",
            (
                ALICE_ID, json.dumps({"org_id": ORG_A_ID}),
                BOB_ID, json.dumps({"org_id": ORG_A_ID}),
                EVE_ID, json.dumps({"org_id": ORG_A_ID}),
            ),
        )

        # Seed organizations
        cur.execute(
            "INSERT INTO organizations (id, name, slug) VALUES (%s, 'Org A', 'org-a'), (%s, 'Org B', 'org-b')",
            (ORG_A_ID, ORG_B_ID),
        )

        # Seed org memberships
        cur.execute(
            "INSERT INTO org_members (org_id, user_id, role) VALUES (%s, %s, 'owner'), (%s, %s, 'member')",
            (ORG_A_ID, ALICE_ID, ORG_A_ID, BOB_ID),
        )

        # Seed project
        cur.execute(
            "INSERT INTO projects (id, org_id, name, created_by) VALUES (%s, %s, 'Project Alpha', %s)",
            (PROJECT_A_ID, ORG_A_ID, ALICE_ID),
        )

        # Seed documents:
        #   DOC_A = confidential, created by Alice
        #   DOC_B = internal, created by Bob
        cur.execute(
            "INSERT INTO documents (id, project_id, title, content, classification, created_by) VALUES "
            "(%s, %s, 'Confidential Doc', 'secret data', 'confidential', %s),"
            "(%s, %s, 'Internal Doc', 'internal info', 'internal', %s)",
            (DOC_A_ID, PROJECT_A_ID, ALICE_ID, DOC_B_ID, PROJECT_A_ID, BOB_ID),
        )

        # Seed audit log entry
        cur.execute(
            "INSERT INTO audit_log (id, table_name, action, row_id, actor_id) "
            "VALUES (%s, 'documents', 'INSERT', %s, %s)",
            (AUDIT_ENTRY_ID, DOC_A_ID, ALICE_ID),
        )
    conn.close()


# ===========================================================================
# Security Tests — Attack Prevention
# ===========================================================================


def test_user_metadata_attack_blocked():
    """Eve with spoofed user_metadata.org_id must NOT see org documents."""
    conn = get_conn()
    with conn.cursor() as cur:
        # Eve spoofs user_metadata to claim org membership, but has no app_metadata org
        authenticate_as(cur, EVE_ID, app_metadata={}, user_metadata={"org_id": ORG_A_ID})
        cur.execute("SELECT id FROM documents")
        rows = cur.fetchall()
        reset(cur)
    conn.close()
    assert len(rows) == 0, (
        f"user_metadata vulnerability: Eve saw {len(rows)} documents via spoofed org_id"
    )


def test_confidential_not_visible_to_org_members():
    """Confidential documents must not be visible to org members without explicit shares."""
    conn = get_conn()
    with conn.cursor() as cur:
        authenticate_as(cur, BOB_ID, app_metadata={"org_id": ORG_A_ID})
        cur.execute(
            "SELECT id FROM documents WHERE classification = 'confidential'"
        )
        rows = cur.fetchall()
        doc_ids = [str(r[0]) for r in rows]
        reset(cur)
    conn.close()
    assert DOC_A_ID not in doc_ids, (
        "Confidential document visible to org member without explicit share or creator access"
    )


def test_security_definer_not_in_public_schema():
    """get_user_role function must not exist in the public schema."""
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM pg_proc p "
            "JOIN pg_namespace n ON p.pronamespace = n.oid "
            "WHERE p.proname = 'get_user_role' AND n.nspname = 'public'"
        )
        found = cur.fetchone() is not None
    conn.close()
    assert not found, "get_user_role must not be in the public schema (search_path injection risk)"


def test_security_definer_in_private_schema():
    """get_user_role must exist in private schema as SECURITY DEFINER with SET search_path."""
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT p.prosecdef, p.proconfig "
            "FROM pg_proc p "
            "JOIN pg_namespace n ON p.pronamespace = n.oid "
            "WHERE p.proname = 'get_user_role' AND n.nspname = 'private'"
        )
        row = cur.fetchone()
    conn.close()
    assert row is not None, "get_user_role must exist in the private schema"
    assert row[0] is True, "get_user_role must be SECURITY DEFINER"
    proconfig = row[1] or []
    has_search_path = any("search_path" in str(c) for c in proconfig)
    assert has_search_path, "get_user_role must have SET search_path configured"


def test_view_has_security_invoker():
    """document_overview view must have security_invoker = true."""
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT reloptions FROM pg_class "
            "WHERE relname = 'document_overview' AND relkind = 'v'"
        )
        row = cur.fetchone()
    conn.close()
    assert row is not None, "document_overview view must exist"
    reloptions = row[0] or []
    has_invoker = any("security_invoker=true" in str(opt) for opt in reloptions)
    assert has_invoker, "document_overview must use security_invoker = true"


def test_view_blocks_unauthorized_access():
    """Eve must not see documents through the document_overview view."""
    conn = get_conn()
    with conn.cursor() as cur:
        authenticate_as(cur, EVE_ID, app_metadata={}, user_metadata={})
        cur.execute("SELECT id FROM document_overview")
        rows = cur.fetchall()
        reset(cur)
    conn.close()
    assert len(rows) == 0, (
        f"View leaks data: Eve saw {len(rows)} rows through document_overview"
    )


def test_share_insert_requires_document_access():
    """Users must not be able to share documents they have no access to."""
    conn = get_conn()
    insert_succeeded = False
    share_id = str(uuid.uuid4())
    try:
        with conn.cursor() as cur:
            authenticate_as(cur, EVE_ID, app_metadata={}, user_metadata={})
            cur.execute(
                "INSERT INTO document_shares (id, document_id, shared_with, permission, shared_by) "
                "VALUES (%s, %s, %s, 'read', %s)",
                (share_id, DOC_A_ID, BOB_ID, EVE_ID),
            )
            insert_succeeded = True
    except (psycopg2.errors.InsufficientPrivilege, psycopg2.errors.RaiseException,
            psycopg2.errors.InternalError):
        pass
    finally:
        conn.close()

    if insert_succeeded:
        # Clean up the unauthorized share
        cleanup = get_conn()
        with cleanup.cursor() as cur:
            cur.execute("DELETE FROM document_shares WHERE id = %s", (share_id,))
        cleanup.close()

    assert not insert_succeeded, (
        "Share escalation: Eve created a share for a document she has no access to"
    )


def test_audit_log_delete_blocked():
    """Authenticated users must not be able to delete audit log entries."""
    conn = get_conn()
    with conn.cursor() as cur:
        authenticate_as(cur, ALICE_ID, app_metadata={"org_id": ORG_A_ID})
        cur.execute("DELETE FROM audit_log WHERE actor_id = %s", (ALICE_ID,))
        deleted = cur.rowcount
        reset(cur)
    conn.close()

    if deleted > 0:
        # Restore the audit entry for other tests
        restore = get_conn()
        with restore.cursor() as cur:
            cur.execute(
                "INSERT INTO audit_log (id, table_name, action, row_id, actor_id) "
                "VALUES (%s, 'documents', 'INSERT', %s, %s) ON CONFLICT DO NOTHING",
                (AUDIT_ENTRY_ID, DOC_A_ID, ALICE_ID),
            )
        restore.close()

    assert deleted == 0, (
        f"Audit tampering: authenticated user deleted {deleted} audit log entries"
    )


def test_org_members_not_visible_to_anon():
    """The anon role must not be able to read org_members."""
    conn = get_conn()
    with conn.cursor() as cur:
        switch_to_anon(cur)
        cur.execute("SELECT count(*) FROM org_members")
        count = cur.fetchone()[0]
        reset(cur)
    conn.close()
    assert count == 0, f"Anon role saw {count} org_members rows (policy missing TO authenticated)"


def test_auth_uid_calls_wrapped_in_select():
    """All auth.uid()/auth.jwt() in policy expressions must use (SELECT ...) wrapper."""
    with open("/app/policies.sql", "r") as f:
        content = f.read()

    # Find all CREATE POLICY blocks in the source file
    for match in re.finditer(
        r'CREATE\s+POLICY\s+"(\w+)"(.*?);',
        content,
        flags=re.DOTALL | re.IGNORECASE,
    ):
        policy_name = match.group(1)
        policy_text = match.group(2)

        # Remove properly wrapped calls: (select auth.uid()) and (select auth.jwt())
        cleaned = re.sub(
            r"\(\s*select\s+auth\.(uid|jwt)\(\)\s*\)",
            "WRAPPED_CALL",
            policy_text,
            flags=re.IGNORECASE,
        )
        bare = re.findall(r"auth\.(uid|jwt)\(\)", cleaned, flags=re.IGNORECASE)
        if bare:
            pytest.fail(
                f"Policy '{policy_name}' has unwrapped auth.{bare[0]}() in expression. "
                f"Wrap in (SELECT ...) for per-statement caching."
            )


# ===========================================================================
# Regression Tests — Legitimate Access
# ===========================================================================


def test_alice_can_see_own_confidential_documents():
    """Document creator must be able to see their own confidential documents."""
    conn = get_conn()
    with conn.cursor() as cur:
        authenticate_as(cur, ALICE_ID, app_metadata={"org_id": ORG_A_ID})
        cur.execute("SELECT id FROM documents WHERE classification = 'confidential'")
        rows = cur.fetchall()
        doc_ids = [str(r[0]) for r in rows]
        reset(cur)
    conn.close()
    assert DOC_A_ID in doc_ids, "Alice must see her own confidential document"


def test_bob_can_see_non_confidential_org_documents():
    """Org member must see non-confidential documents but not confidential ones they lack shares for."""
    conn = get_conn()
    with conn.cursor() as cur:
        authenticate_as(cur, BOB_ID, app_metadata={"org_id": ORG_A_ID})
        cur.execute("SELECT id FROM documents")
        rows = cur.fetchall()
        doc_ids = [str(r[0]) for r in rows]
        reset(cur)
    conn.close()
    # Bob should see DOC_B (his own, internal classification)
    assert DOC_B_ID in doc_ids, "Bob must see his own internal document"
    # Bob should NOT see DOC_A (confidential, created by Alice, no share)
    assert DOC_A_ID not in doc_ids, (
        "Confidential document visible to org member without explicit share or creator access"
    )


def test_confidential_visible_via_share():
    """Users with explicit shares can see confidential documents."""
    share_id = str(uuid.uuid4())
    setup_conn = get_conn()
    with setup_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO document_shares (id, document_id, shared_with, permission, shared_by) "
            "VALUES (%s, %s, %s, 'read', %s)",
            (share_id, DOC_A_ID, BOB_ID, ALICE_ID),
        )
    setup_conn.close()

    conn = get_conn()
    with conn.cursor() as cur:
        authenticate_as(cur, BOB_ID, app_metadata={"org_id": ORG_A_ID})
        cur.execute("SELECT id FROM documents WHERE id = %s", (DOC_A_ID,))
        rows = cur.fetchall()
        reset(cur)
    conn.close()

    # Clean up
    cleanup = get_conn()
    with cleanup.cursor() as cur:
        cur.execute("DELETE FROM document_shares WHERE id = %s", (share_id,))
    cleanup.close()

    assert len(rows) == 1, "Bob must see confidential document when explicitly shared with him"


def test_alice_can_delete_own_document():
    """Org owner must be able to delete their own documents (tests private.get_user_role)."""
    conn = get_conn()
    temp_doc_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        # Create a temporary document as superuser
        cur.execute(
            "INSERT INTO documents (id, project_id, title, content, classification, created_by) "
            "VALUES (%s, %s, 'Temp Doc', 'temp', 'internal', %s)",
            (temp_doc_id, PROJECT_A_ID, ALICE_ID),
        )
        # Switch to Alice and try to delete
        authenticate_as(cur, ALICE_ID, app_metadata={"org_id": ORG_A_ID})
        cur.execute("DELETE FROM documents WHERE id = %s", (temp_doc_id,))
        deleted = cur.rowcount
        reset(cur)
        # Clean up if delete failed
        if deleted == 0:
            cur.execute("DELETE FROM documents WHERE id = %s", (temp_doc_id,))
    conn.close()
    assert deleted == 1, (
        "Alice (org owner) must be able to delete her own documents. "
        "Ensure private.get_user_role is properly callable."
    )


def test_alice_can_share_own_document():
    """Document creator must be able to share their own documents."""
    conn = get_conn()
    share_id = str(uuid.uuid4())
    shared = False
    try:
        with conn.cursor() as cur:
            authenticate_as(cur, ALICE_ID, app_metadata={"org_id": ORG_A_ID})
            cur.execute(
                "INSERT INTO document_shares (id, document_id, shared_with, permission, shared_by) "
                "VALUES (%s, %s, %s, 'read', %s)",
                (share_id, DOC_A_ID, EVE_ID, ALICE_ID),
            )
            shared = True
            reset(cur)
            # Clean up
            cur.execute("DELETE FROM document_shares WHERE id = %s", (share_id,))
    except Exception:
        pass
    finally:
        conn.close()
    assert shared, "Alice must be able to share documents she created"


def test_write_share_holder_can_reshare():
    """Users with write-permission shares can re-share the document."""
    share_id1 = str(uuid.uuid4())
    share_id2 = str(uuid.uuid4())
    reshared = False

    # Create initial write share as superuser
    setup_conn = get_conn()
    with setup_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO document_shares (id, document_id, shared_with, permission, shared_by) "
            "VALUES (%s, %s, %s, 'write', %s)",
            (share_id1, DOC_A_ID, BOB_ID, ALICE_ID),
        )
    setup_conn.close()

    # Try to reshare as Bob (who has a write share)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            authenticate_as(cur, BOB_ID, app_metadata={"org_id": ORG_A_ID})
            cur.execute(
                "INSERT INTO document_shares (id, document_id, shared_with, permission, shared_by) "
                "VALUES (%s, %s, %s, 'read', %s)",
                (share_id2, DOC_A_ID, EVE_ID, BOB_ID),
            )
            reshared = True
    except Exception:
        pass
    finally:
        conn.close()

    # Clean up
    cleanup = get_conn()
    with cleanup.cursor() as cur:
        cur.execute("DELETE FROM document_shares WHERE id IN (%s, %s)", (share_id1, share_id2))
    cleanup.close()

    assert reshared, "User with write-permission share must be able to re-share the document"
