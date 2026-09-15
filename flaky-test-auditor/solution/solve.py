#!/usr/bin/env python3
"""
Solution for IDoFT cross-dataset reconciliation task.

Fixes the buggy odr_category_consistency check (adds test_name to JOIN)
and implements 4 missing checks: developer_fixed_no_fix_record,
odr_type_conflict, orphaned_odr_reference, orphaned_fix_record.

"""

import sqlite3
import json

DB_PATH = "/app/idoft.db"
REPORT_PATH = "/app/reconciliation_report.json"

ODR_TYPE_TO_CATEGORY = {
    "victim": "OD-Vic",
    "brittle": "OD-Brit",
}


class ReconciliationEngine:
    def __init__(self, db_path=DB_PATH):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.violations = []

    def _add(self, category, source_table, source_id, details):
        self.violations.append({
            "category": category,
            "source_table": source_table,
            "source_id": source_id,
            "details": details,
        })

    def check_moved_to_gradle(self):
        cursor = self.conn.execute("""
            SELECT p.id, p.project_url, p.test_name
            FROM pr_data p
            LEFT JOIN gr_data g
              ON p.project_url = g.project_url AND p.test_name = g.test_name
            WHERE p.status = 'MovedToGradle' AND g.id IS NULL
        """)
        for row in cursor:
            self._add(
                "moved_to_gradle_unmatched", "pr_data", row["id"],
                f"Test '{row['test_name']}' in {row['project_url']} has status "
                f"MovedToGradle but no matching entry exists in gr_data"
            )

    def check_odr_category_consistency(self):
        """FIXED: Added o.od_test = p.test_name to JOIN condition.
        The original bug joined only on project_url, producing false positives
        for non-OD tests in projects that happen to have any OD test in odr_tests."""
        cursor = self.conn.execute("""
            SELECT DISTINCT p.id, p.test_name, p.category, p.project_url
            FROM pr_data p
            JOIN odr_tests o
              ON p.project_url = o.project_url AND p.test_name = o.od_test
            WHERE p.category NOT IN ('OD', 'OD-Vic', 'OD-Brit')
        """)
        for row in cursor:
            self._add(
                "odr_category_mismatch", "pr_data", row["id"],
                f"Test '{row['test_name']}' is categorized as {row['category']} "
                f"but appears in odr_tests (should be OD/OD-Vic/OD-Brit)"
            )

    def check_cross_build_duplicates(self):
        cursor = self.conn.execute("""
            SELECT p.id AS pr_id, g.id AS gr_id, p.project_url, p.test_name
            FROM pr_data p
            JOIN gr_data g ON p.project_url = g.project_url
                          AND p.test_name = g.test_name
        """)
        for row in cursor:
            self._add(
                "cross_build_duplicate", "pr_data", row["pr_id"],
                f"Test '{row['test_name']}' in {row['project_url']} appears in both "
                f"pr_data (Maven, id={row['pr_id']}) and gr_data (Gradle, id={row['gr_id']})"
            )

    def check_developer_fixed_records(self):
        """NEW: DeveloperFixed entries must have corresponding tic_fic records."""
        for table in ["pr_data", "gr_data"]:
            cursor = self.conn.execute(f"""
                SELECT t.id, t.project_url, t.test_name
                FROM {table} t
                LEFT JOIN tic_fic_data f
                  ON t.project_url = f.project_url AND t.test_name = f.test_name
                WHERE t.status = 'DeveloperFixed' AND f.id IS NULL
            """)
            for row in cursor:
                self._add(
                    "developer_fixed_no_fix_record", table, row["id"],
                    f"Test '{row['test_name']}' in {row['project_url']} has status "
                    f"DeveloperFixed but no matching fix record in tic_fic_data"
                )

    def check_odr_type_conflicts(self):
        """NEW: od_test_type (victim/brittle) must be consistent with the
        specific OD sub-category (OD-Vic/OD-Brit). OD (generic) is acceptable
        for either type. Conflicts: victim+OD-Brit or brittle+OD-Vic."""
        cursor = self.conn.execute("""
            SELECT o.id AS odr_id, p.id AS pr_id, p.test_name, p.category,
                   o.od_test_type, p.project_url
            FROM odr_tests o
            JOIN pr_data p
              ON o.project_url = p.project_url AND o.od_test = p.test_name
            WHERE (o.od_test_type = 'victim' AND p.category = 'OD-Brit')
               OR (o.od_test_type = 'brittle' AND p.category = 'OD-Vic')
        """)
        for row in cursor:
            expected = ODR_TYPE_TO_CATEGORY.get(row["od_test_type"], "unknown")
            self._add(
                "odr_type_conflict", "pr_data", row["pr_id"],
                f"Test '{row['test_name']}' has category {row['category']} but "
                f"odr_tests classifies it as {row['od_test_type']} (expected {expected})"
            )

    def check_orphaned_odr_references(self):
        """NEW: odr_tests entries must reference a test that exists in pr_data or gr_data."""
        cursor = self.conn.execute("""
            SELECT o.id, o.project_url, o.od_test
            FROM odr_tests o
            LEFT JOIN pr_data p
              ON o.project_url = p.project_url AND o.od_test = p.test_name
            LEFT JOIN gr_data g
              ON o.project_url = g.project_url AND o.od_test = g.test_name
            WHERE p.id IS NULL AND g.id IS NULL
        """)
        for row in cursor:
            self._add(
                "orphaned_odr_reference", "odr_tests", row["id"],
                f"ODR entry for '{row['od_test']}' in {row['project_url']} "
                f"has no matching entry in pr_data or gr_data"
            )

    def check_orphaned_fix_records(self):
        """NEW: tic_fic_data entries must reference a test in pr_data or gr_data."""
        cursor = self.conn.execute("""
            SELECT t.id, t.project_url, t.test_name
            FROM tic_fic_data t
            LEFT JOIN pr_data p
              ON t.project_url = p.project_url AND t.test_name = p.test_name
            LEFT JOIN gr_data g
              ON t.project_url = g.project_url AND t.test_name = g.test_name
            WHERE p.id IS NULL AND g.id IS NULL
        """)
        for row in cursor:
            self._add(
                "orphaned_fix_record", "tic_fic_data", row["id"],
                f"Fix record for '{row['test_name']}' in {row['project_url']} "
                f"has no matching entry in pr_data or gr_data"
            )

    def run_all(self):
        self.violations = []
        self.check_moved_to_gradle()
        self.check_odr_category_consistency()
        self.check_cross_build_duplicates()
        self.check_developer_fixed_records()
        self.check_odr_type_conflicts()
        self.check_orphaned_odr_references()
        self.check_orphaned_fix_records()
        return self.generate_report()

    def generate_report(self):
        by_category = {}
        for v in self.violations:
            cat = v["category"]
            by_category[cat] = by_category.get(cat, 0) + 1

        report = {
            "reconciliation_results": {
                "total_violations": len(self.violations),
                "by_category": by_category,
                "violations": self.violations,
            }
        }

        with open(REPORT_PATH, "w") as f:
            json.dump(report, f, indent=2)

        return report


if __name__ == "__main__":
    engine = ReconciliationEngine()
    report = engine.run_all()
    total = report["reconciliation_results"]["total_violations"]
    print(f"Reconciliation complete: {total} violations found")
    for cat, count in sorted(report["reconciliation_results"]["by_category"].items()):
        print(f"  {cat}: {count}")
