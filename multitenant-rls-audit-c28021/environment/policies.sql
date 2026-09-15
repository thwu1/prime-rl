
-- RLS policies, helper functions, and views for the multi-tenant document system.
-- This file contains security vulnerabilities that must be identified and fixed.

---------------------------------------------
-- HELPER FUNCTIONS
---------------------------------------------

-- Returns the role of the current user in a given organization
CREATE OR REPLACE FUNCTION public.get_user_role(p_org_id uuid)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    RETURN (SELECT role FROM public.org_members WHERE user_id = auth.uid() AND org_id = p_org_id);
END;
$$;

GRANT EXECUTE ON FUNCTION public.get_user_role(uuid) TO authenticated;

---------------------------------------------
-- ORGANIZATION POLICIES
---------------------------------------------

CREATE POLICY "org_select" ON organizations FOR SELECT TO authenticated
USING (
    EXISTS (
        SELECT 1 FROM org_members
        WHERE org_members.org_id = organizations.id
        AND org_members.user_id = (select auth.uid())
    )
);

CREATE POLICY "org_insert" ON organizations FOR INSERT TO authenticated
WITH CHECK (true);

---------------------------------------------
-- ORG_MEMBERS POLICIES
---------------------------------------------

CREATE POLICY "org_members_select" ON org_members FOR SELECT
USING (user_id = auth.uid());

CREATE POLICY "org_members_insert" ON org_members FOR INSERT TO authenticated
WITH CHECK (
    EXISTS (
        SELECT 1 FROM org_members existing
        WHERE existing.org_id = org_members.org_id
        AND existing.user_id = (select auth.uid())
        AND existing.role IN ('owner', 'admin')
    )
);

---------------------------------------------
-- PROJECTS POLICIES
---------------------------------------------

CREATE POLICY "projects_select" ON projects FOR SELECT TO authenticated
USING (
    EXISTS (
        SELECT 1 FROM org_members
        WHERE org_members.org_id = projects.org_id
        AND org_members.user_id = (select auth.uid())
    )
);

CREATE POLICY "projects_insert" ON projects FOR INSERT TO authenticated
WITH CHECK (
    EXISTS (
        SELECT 1 FROM org_members
        WHERE org_members.org_id = projects.org_id
        AND org_members.user_id = (select auth.uid())
        AND org_members.role IN ('owner', 'admin', 'member')
    )
);

---------------------------------------------
-- DOCUMENTS POLICIES
---------------------------------------------

CREATE POLICY "docs_select" ON documents FOR SELECT TO authenticated
USING (
    created_by = auth.uid()
    OR EXISTS (
        SELECT 1 FROM document_shares ds
        WHERE ds.document_id = documents.id
        AND ds.shared_with = auth.uid()
    )
    OR EXISTS (
        SELECT 1 FROM projects p
        WHERE p.id = documents.project_id
        AND p.org_id = (auth.jwt()->'user_metadata'->>'org_id')::uuid
    )
);

CREATE POLICY "docs_insert" ON documents FOR INSERT TO authenticated
WITH CHECK (
    created_by = (select auth.uid())
    AND EXISTS (
        SELECT 1 FROM projects p
        JOIN org_members om ON om.org_id = p.org_id
        WHERE p.id = documents.project_id
        AND om.user_id = (select auth.uid())
        AND om.role IN ('owner', 'admin', 'member')
    )
);

CREATE POLICY "docs_update" ON documents FOR UPDATE TO authenticated
USING (created_by = (select auth.uid()))
WITH CHECK (created_by = (select auth.uid()));

CREATE POLICY "docs_delete" ON documents FOR DELETE TO authenticated
USING (
    created_by = (select auth.uid())
    AND public.get_user_role(
        (SELECT p.org_id FROM projects p WHERE p.id = documents.project_id)
    ) IN ('owner', 'admin')
);

---------------------------------------------
-- DOCUMENT_SHARES POLICIES
---------------------------------------------

CREATE POLICY "shares_select" ON document_shares FOR SELECT TO authenticated
USING (
    shared_with = (select auth.uid()) OR shared_by = (select auth.uid())
);

CREATE POLICY "shares_insert" ON document_shares FOR INSERT TO authenticated
WITH CHECK (
    shared_by = (select auth.uid())
);

CREATE POLICY "shares_delete" ON document_shares FOR DELETE TO authenticated
USING (shared_by = (select auth.uid()));

---------------------------------------------
-- AUDIT_LOG POLICIES
---------------------------------------------

CREATE POLICY "audit_select" ON audit_log FOR SELECT TO authenticated
USING (actor_id = (select auth.uid()));

CREATE POLICY "audit_insert" ON audit_log FOR INSERT TO authenticated
WITH CHECK (actor_id = (select auth.uid()));

CREATE POLICY "audit_delete" ON audit_log FOR DELETE TO authenticated
USING (actor_id = (select auth.uid()));

---------------------------------------------
-- VIEWS
---------------------------------------------

CREATE VIEW document_overview AS
SELECT d.id, d.title, d.classification, d.created_at,
       p.name as project_name, o.name as org_name, o.id as org_id
FROM documents d
JOIN projects p ON d.project_id = p.id
JOIN organizations o ON p.org_id = o.id;

GRANT SELECT ON document_overview TO authenticated;
GRANT SELECT ON document_overview TO anon;
