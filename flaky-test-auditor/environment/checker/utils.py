"""Utility functions for the IDoFT format checker."""



class ErrorTracker:
    """Tracks validation errors and warnings during format checking."""

    def __init__(self):
        self.errors = []
        self.warnings = []

    def add_error(self, filename, row, vtype, field=None, value=None, details=""):
        self.errors.append({
            "file": filename,
            "row": row,
            "type": vtype,
            "field": field,
            "value": value,
            "details": details,
        })

    def add_warning(self, filename, row, message):
        self.warnings.append({
            "file": filename,
            "row": row,
            "message": message,
        })

    def get_report(self):
        by_file = {}
        by_type = {}
        for e in self.errors:
            f = e["file"]
            t = e["type"]
            by_file[f] = by_file.get(f, 0) + 1
            by_type[t] = by_type.get(t, 0) + 1

        return {
            "violations": self.errors,
            "summary": {
                "total": len(self.errors),
                "by_file": by_file,
                "by_type": by_type,
            },
        }
