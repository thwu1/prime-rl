"""
Partial reconciliation engine for IDoFT cross-dataset integrity analysis.

Implements a subset of cross-referential integrity checks between the
interlinked IDoFT tables. Additional checks may be needed for complete
coverage of the data model's semantic constraints.
"""
import sqlite3
import json

DB_PATH = "/app/idoft.db"
REPORT_PATH = "/app/reconciliation_report.json"

OD_CATEGORIES = {"OD", "OD-Vic", "OD-Brit"}


class ReconciliationEngine:
    def __init__(self, db_path=DB_PATH):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.violations = []

    def _add_violation(self, category, source_table, source_id, details):
        self.violations.append({
            "category": category,
            "source_table": source_table,
            "source_id": source_id,
            "details": details,
        })

    def check_moved_to_gradle(self):
        """Check that MovedToGradle entries in pr_data have matching gr_data records."""
        cursor = self.conn.execute("""
            SELECT p.id, p.project_url, p.test_name
            FROM pr_data p
            LEFT JOIN gr_data g
              ON p.project_url = g.project_url AND p.test_name = g.test_name
            WHERE p.status = 'MovedToGradle' AND g.id IS NULL
        """)
        for row in cursor:
            self._add_violation(
                "moved_to_gradle_unmatched", "pr_data", row["id"],
                f"Test '{row['test_name']}' in {row['project_url']} has status "
                f"MovedToGradle but no matching entry exists in gr_data"
            )

    def check_odr_category_consistency(self):
        """Check that tests appearing in odr_tests have OD-family categories
        in the main dataset tables."""
        cursor = self.conn.execute("""
            SELECT DISTINCT p.id, p.test_name, p.category, p.project_url
            FROM pr_data p
            JOIN odr_tests o ON p.project_url = o.project_url
            WHERE p.category NOT IN ('OD', 'OD-Vic', 'OD-Brit')
        """)
        for row in cursor:
            self._add_violation(
                "odr_category_mismatch", "pr_data", row["id"],
                f"Test '{row['test_name']}' is categorized as {row['category']} "
                f"but appears in odr_tests (should be OD/OD-Vic/OD-Brit)"
            )

    def check_cross_build_duplicates(self):
        """Check for tests appearing in both pr_data (Maven) and gr_data (Gradle)."""
        cursor = self.conn.execute("""
            SELECT p.id AS pr_id, g.id AS gr_id, p.project_url, p.test_name
            FROM pr_data p
            JOIN gr_data g ON p.project_url = g.project_url
                          AND p.test_name = g.test_name
        """)
        for row in cursor:
            self._add_violation(
                "cross_build_duplicate", "pr_data", row["pr_id"],
                f"Test '{row['test_name']}' in {row['project_url']} appears in both "
                f"pr_data (Maven, id={row['pr_id']}) and gr_data (Gradle, id={row['gr_id']})"
            )

    def run_all(self):
        """Execute all reconciliation checks and generate the report."""
        self.violations = []
        self.check_moved_to_gradle()
        self.check_odr_category_consistency()
        self.check_cross_build_duplicates()
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
