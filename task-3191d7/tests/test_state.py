"""Tests for the NexAuth secret token scanner.

Verification matches on unique token strings — each generated token
has a unique random payload, so the token string alone identifies it.

"""


class TestReportStructure:
    def test_report_has_tokens(self, report):
        assert "tokens" in report, "report.json missing 'tokens' key"
        assert isinstance(report["tokens"], list), "'tokens' must be a list"

    def test_report_has_summary(self, report):
        assert "summary" in report, "report.json missing 'summary' key"
        summary = report["summary"]
        for key in ("total", "valid", "invalid", "by_type"):
            assert key in summary, f"summary missing '{key}' key"

    def test_token_entries_have_required_fields(self, report):
        for i, entry in enumerate(report["tokens"]):
            for field in ("file", "token", "type", "valid"):
                assert field in entry, f"Token entry {i} missing '{field}' field"


class TestTokenDetection:
    def test_no_false_negatives(self, report, ground_truth):
        """Every token in the ground truth must be found in the report."""
        report_tokens = {t["token"] for t in report["tokens"]}
        missing = []
        for gt in ground_truth:
            if gt["token"] not in report_tokens:
                missing.append(
                    f"  {gt['token'][:25]}... (type={gt['type']}, "
                    f"valid={gt['valid']})"
                )
        assert not missing, (
            f"Missing {len(missing)} tokens from report:\n"
            + "\n".join(missing)
        )

    def test_no_false_positives(self, report, ground_truth):
        """Every token in the report must exist in the ground truth."""
        gt_tokens = {t["token"] for t in ground_truth}
        spurious = []
        for rt in report["tokens"]:
            if rt["token"] not in gt_tokens:
                spurious.append(
                    f"  {rt['token'][:25]}... (type={rt['type']})"
                )
        assert not spurious, (
            f"Found {len(spurious)} false positive tokens:\n"
            + "\n".join(spurious)
        )


class TestClassification:
    def test_validity_correct(self, report, ground_truth):
        """Each token's 'valid' field must match ground truth."""
        gt_map = {t["token"]: t["valid"] for t in ground_truth}
        wrong = []
        for rt in report["tokens"]:
            if rt["token"] in gt_map and rt["valid"] != gt_map[rt["token"]]:
                wrong.append(
                    f"  {rt['token'][:25]}... "
                    f"expected valid={gt_map[rt['token']]}, "
                    f"got valid={rt['valid']}"
                )
        assert not wrong, (
            f"Wrong validity for {len(wrong)} tokens:\n" + "\n".join(wrong)
        )

    def test_type_correct(self, report, ground_truth):
        """Each token's 'type' field must match ground truth."""
        gt_map = {t["token"]: t["type"] for t in ground_truth}
        wrong = []
        for rt in report["tokens"]:
            if rt["token"] in gt_map and rt["type"] != gt_map[rt["token"]]:
                wrong.append(
                    f"  {rt['token'][:25]}... "
                    f"expected type={gt_map[rt['token']]}, "
                    f"got type={rt['type']}"
                )
        assert not wrong, (
            f"Wrong type for {len(wrong)} tokens:\n" + "\n".join(wrong)
        )


class TestSummary:
    def test_total_count(self, report, ground_truth):
        assert report["summary"]["total"] == len(ground_truth), (
            f"Summary total {report['summary']['total']} "
            f"!= expected {len(ground_truth)}"
        )

    def test_valid_count(self, report, ground_truth):
        expected = sum(1 for t in ground_truth if t["valid"])
        assert report["summary"]["valid"] == expected, (
            f"Summary valid {report['summary']['valid']} "
            f"!= expected {expected}"
        )

    def test_invalid_count(self, report, ground_truth):
        expected = sum(1 for t in ground_truth if not t["valid"])
        assert report["summary"]["invalid"] == expected, (
            f"Summary invalid {report['summary']['invalid']} "
            f"!= expected {expected}"
        )

    def test_by_type_counts(self, report, ground_truth):
        expected = {}
        for t in ground_truth:
            expected[t["type"]] = expected.get(t["type"], 0) + 1
        assert report["summary"]["by_type"] == expected, (
            f"Summary by_type {report['summary']['by_type']} "
            f"!= expected {expected}"
        )
