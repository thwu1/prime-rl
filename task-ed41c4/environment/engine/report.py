"""FHIR data quality report generator."""


SEARCH_QUERIES = [
    {
        "name": "heart_rate_by_loinc",
        "query": "code=http://loinc.org|8867-4",
        "resource_type": "Observation",
        "params": [("code", "http://loinc.org|8867-4")],
    },
    {
        "name": "january_observations",
        "query": "date=ge2024-01-01&date=le2024-01-31",
        "resource_type": "Observation",
        "params": [("date", "ge2024-01-01"), ("date", "le2024-01-31")],
    },
    {
        "name": "observations_on_jan15",
        "query": "date=2024-01-15",
        "resource_type": "Observation",
        "params": [("date", "2024-01-15")],
    },
    {
        "name": "high_quantity_observations",
        "query": "value-quantity=gt80",
        "resource_type": "Observation",
        "params": [("value-quantity", "gt80")],
    },
    {
        "name": "active_medication_requests",
        "query": "status=active",
        "resource_type": "MedicationRequest",
        "params": [("status", "active")],
    },
    {
        "name": "feb_mar_observations",
        "query": "date=ge2024-02&date=le2024-03",
        "resource_type": "Observation",
        "params": [("date", "ge2024-02"), ("date", "le2024-03")],
    },
]


class ReportGenerator:
    """Generates a FHIR data quality report."""

    def __init__(self, store, ref_checker, search_engine):
        self.store = store
        self.ref_checker = ref_checker
        self.search_engine = search_engine

    def generate(self):
        """Generate the full quality report."""
        report = {}
        report["resource_summary"] = self.store.get_summary()
        report["reference_integrity"] = self.ref_checker.check_all()
        report["search_results"] = self._run_searches()
        return report

    def _run_searches(self):
        results = {}
        for q in SEARCH_QUERIES:
            matched = self.search_engine.search(q["resource_type"], q["params"])
            results[q["name"]] = {
                "query": q["query"],
                "resource_type": q["resource_type"],
                "matched_ids": matched,
                "count": len(matched),
            }
        return results
