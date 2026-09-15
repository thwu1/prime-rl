-- Corrected SQL views for Joos 1W type hierarchy checking
--

-- Rule 1: Class must not extend an interface
DROP VIEW IF EXISTS v_rule1;
CREATE VIEW v_rule1 AS
  SELECT DISTINCT i.child_name AS type, 1 AS rule
  FROM inheritance i
  JOIN types child ON child.canonical_name = i.child_name
  JOIN types parent ON parent.canonical_name = i.parent_name
  WHERE child.kind = 'class'
    AND i.relation = 'extends'
    AND parent.kind = 'interface';

-- Rule 2: Class must not implement a class
DROP VIEW IF EXISTS v_rule2;
CREATE VIEW v_rule2 AS
  SELECT DISTINCT i.child_name AS type, 2 AS rule
  FROM inheritance i
  JOIN types child ON child.canonical_name = i.child_name
  JOIN types parent ON parent.canonical_name = i.parent_name
  WHERE child.kind = 'class'
    AND i.relation = 'implements'
    AND parent.kind = 'class';

-- Rule 3: No repeated interface in implements/extends
DROP VIEW IF EXISTS v_rule3;
CREATE VIEW v_rule3 AS
  SELECT i.child_name AS type, 3 AS rule
  FROM inheritance i
  JOIN types t ON t.canonical_name = i.child_name
  WHERE (t.kind = 'class' AND i.relation = 'implements')
     OR (t.kind = 'interface' AND i.relation = 'extends')
  GROUP BY i.child_name, i.parent_name
  HAVING COUNT(*) > 1;

-- Rule 4: Must not extend a final class
DROP VIEW IF EXISTS v_rule4;
CREATE VIEW v_rule4 AS
  SELECT DISTINCT i.child_name AS type, 4 AS rule
  FROM inheritance i
  JOIN types parent ON parent.canonical_name = i.parent_name
  WHERE i.relation = 'extends'
    AND parent.modifiers LIKE '%"final"%'
    AND parent.kind = 'class';

-- Rule 5: Interface must not extend a class
DROP VIEW IF EXISTS v_rule5;
CREATE VIEW v_rule5 AS
  SELECT DISTINCT i.child_name AS type, 5 AS rule
  FROM inheritance i
  JOIN types child ON child.canonical_name = i.child_name
  JOIN types parent ON parent.canonical_name = i.parent_name
  WHERE child.kind = 'interface'
    AND i.relation = 'extends'
    AND parent.kind = 'class';

-- Combined structural violations
DROP VIEW IF EXISTS v_structural_violations;
CREATE VIEW v_structural_violations AS
  SELECT * FROM v_rule1
  UNION ALL SELECT * FROM v_rule2
  UNION ALL SELECT * FROM v_rule3
  UNION ALL SELECT * FROM v_rule4
  UNION ALL SELECT * FROM v_rule5;

-- FIX: Hierarchy edges for cycle detection
-- For interfaces, use 'extends' (was incorrectly 'implements')
DROP VIEW IF EXISTS v_hierarchy_edges;
CREATE VIEW v_hierarchy_edges AS
  SELECT i.child_name, i.parent_name
  FROM inheritance i
  JOIN types t ON t.canonical_name = i.child_name
  WHERE t.kind = 'class'
  UNION ALL
  SELECT i.child_name, i.parent_name
  FROM inheritance i
  JOIN types t ON t.canonical_name = i.child_name
  WHERE t.kind = 'interface' AND i.relation = 'extends';
