#!/usr/bin/env python3
"""
Analyze and fix security vulnerabilities in /app/policies.sql.

"""
import re

with open("/app/policies.sql", "r") as f:
    content = f.read()

# ---------------------------------------------------------------
# Fix 1+8: Replace user_metadata-based org check with org_members join
# AND add classification guard for confidential documents.
# Vulnerabilities:
#   - user_metadata is modifiable by end users
#   - confidential docs should only be visible to creator/share holders
# ---------------------------------------------------------------
content = content.replace(
    """    OR EXISTS (
        SELECT 1 FROM projects p
        WHERE p.id = documents.project_id
        AND p.org_id = (auth.jwt()->'user_metadata'->>'org_id')::uuid
    )""",
    """    OR (
        documents.classification != 'confidential'
        AND EXISTS (
            SELECT 1 FROM org_members om
            JOIN projects p ON p.org_id = om.org_id
            WHERE p.id = documents.project_id
            AND om.user_id = (select auth.uid())
        )
    )""",
)

# ---------------------------------------------------------------
# Fix 6a: Wrap bare auth.uid() calls in (select ...) in docs_select
# Performance: enables per-statement caching vs per-row evaluation
# ---------------------------------------------------------------
content = content.replace(
    "    created_by = auth.uid()\n",
    "    created_by = (select auth.uid())\n",
)
content = content.replace(
    "        AND ds.shared_with = auth.uid()\n",
    "        AND ds.shared_with = (select auth.uid())\n",
)

# ---------------------------------------------------------------
# Fix 7: Add TO authenticated and wrap auth.uid() in org_members_select
# Security: prevents policy evaluation for anon role
# ---------------------------------------------------------------
content = content.replace(
    'CREATE POLICY "org_members_select" ON org_members FOR SELECT\n'
    "USING (user_id = auth.uid());",
    'CREATE POLICY "org_members_select" ON org_members FOR SELECT TO authenticated\n'
    "USING (user_id = (select auth.uid()));",
)

# ---------------------------------------------------------------
# Fix 2: Move get_user_role from public to private schema
# Security: SECURITY DEFINER in public schema allows search_path injection
# ---------------------------------------------------------------
content = content.replace(
    "CREATE OR REPLACE FUNCTION public.get_user_role(p_org_id uuid)\n"
    "RETURNS text\n"
    "LANGUAGE plpgsql\n"
    "SECURITY DEFINER\n"
    "AS $$",
    "CREATE OR REPLACE FUNCTION private.get_user_role(p_org_id uuid)\n"
    "RETURNS text\n"
    "LANGUAGE plpgsql\n"
    "SECURITY DEFINER\n"
    "SET search_path = ''\n"
    "AS $$",
)

content = content.replace(
    "GRANT EXECUTE ON FUNCTION public.get_user_role(uuid) TO authenticated;",
    "GRANT USAGE ON SCHEMA private TO authenticated;\n"
    "GRANT EXECUTE ON FUNCTION private.get_user_role(uuid) TO authenticated;",
)

# Update the docs_delete policy reference from public to private schema
content = content.replace(
    "    AND public.get_user_role(",
    "    AND private.get_user_role(",
)

# ---------------------------------------------------------------
# Fix 4a: Create a SECURITY DEFINER function to check document access
# without triggering RLS recursion on document_shares.
# ---------------------------------------------------------------
content = content.replace(
    "GRANT EXECUTE ON FUNCTION private.get_user_role(uuid) TO authenticated;",
    "GRANT EXECUTE ON FUNCTION private.get_user_role(uuid) TO authenticated;\n"
    "\n"
    "CREATE OR REPLACE FUNCTION private.user_has_document_access(p_doc_id uuid, p_user_id uuid)\n"
    "RETURNS boolean\n"
    "LANGUAGE sql\n"
    "SECURITY DEFINER\n"
    "SET search_path = ''\n"
    "AS $$\n"
    "    SELECT EXISTS (\n"
    "        SELECT 1 FROM public.documents WHERE id = p_doc_id AND created_by = p_user_id\n"
    "    )\n"
    "    OR EXISTS (\n"
    "        SELECT 1 FROM public.document_shares\n"
    "        WHERE document_id = p_doc_id AND shared_with = p_user_id AND permission = 'write'\n"
    "    );\n"
    "$$;\n"
    "\n"
    "GRANT EXECUTE ON FUNCTION private.user_has_document_access(uuid, uuid) TO authenticated;",
)

# ---------------------------------------------------------------
# Fix 5: Remove audit_delete policy (audit log must be append-only)
# ---------------------------------------------------------------
content = re.sub(
    r'CREATE POLICY "audit_delete" ON audit_log FOR DELETE TO authenticated\n'
    r"USING \(actor_id = \(select auth\.uid\(\)\)\);",
    "-- audit_delete policy removed: audit log is append-only",
    content,
)

# ---------------------------------------------------------------
# Fix 4b: Modify shares_insert to use the access-check function
# instead of directly querying document_shares (avoids infinite recursion)
# ---------------------------------------------------------------
content = content.replace(
    'CREATE POLICY "shares_insert" ON document_shares FOR INSERT TO authenticated\n'
    'WITH CHECK (\n'
    '    shared_by = (select auth.uid())\n'
    ');',
    'CREATE POLICY "shares_insert" ON document_shares FOR INSERT TO authenticated\n'
    'WITH CHECK (\n'
    '    shared_by = (select auth.uid())\n'
    '    AND private.user_has_document_access(document_shares.document_id, (select auth.uid()))\n'
    ');',
)

# ---------------------------------------------------------------
# Fix 3: Add security_invoker = true to document_overview view
# Security: without this, view runs as owner (postgres) bypassing RLS
# ---------------------------------------------------------------
content = content.replace(
    "CREATE VIEW document_overview AS",
    "CREATE VIEW document_overview WITH (security_invoker = true) AS",
)

with open("/app/policies.sql", "w") as f:
    f.write(content)

print("Fixed all security vulnerabilities in /app/policies.sql:")
print("  1. Replaced user_metadata with org_members join in docs_select")
print("  2. Moved get_user_role to private schema with SET search_path = ''")
print("  3. Added security_invoker = true to document_overview view")
print("  4. Added document access check via SECURITY DEFINER function to shares_insert")
print("  5. Removed audit_delete policy (append-only enforcement)")
print("  6. Wrapped all bare auth.uid()/auth.jwt() calls in (select ...)")
print("  7. Added TO authenticated to org_members_select policy")
print("  8. Added classification != 'confidential' guard to org membership access")
