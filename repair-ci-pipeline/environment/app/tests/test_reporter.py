"""Tests for logminer.reporter module."""
import json


def test_build_report_basic():
    """Report is built with correct structure."""
    from logminer.parser import ErrorRecord
    from logminer.localizer import FaultLocation
    from logminer.reporter import build_report

    errors = [
        ErrorRecord(step_name='lint', error_type='lint_error', message='unused import'),
        ErrorRecord(step_name='test', error_type='test_failure', message='assertion failed'),
    ]
    locations = [
        FaultLocation(
            file_path='foo.py',
            line_range=(1, 5),
            reason='unused import',
            confidence=0.9,
        ),
    ]

    report = build_report(errors, locations)
    assert 'fault_locations' in report
    assert len(report['fault_locations']) == 1


def test_report_keys():
    """Report must contain 'error_summary' (not a misspelling)."""
    from logminer.reporter import build_report

    report = build_report([], [])
    assert 'error_summary' in report, (
        f"Missing 'error_summary' key, got keys: {sorted(report.keys())}"
    )


def test_serialize_json():
    """Report serializes to valid JSON."""
    from logminer.reporter import build_report, serialize_report
    from logminer.parser import ErrorRecord

    report = build_report(
        [ErrorRecord(step_name='s', error_type='e', message='m')],
        [],
    )
    serialized = serialize_report(report, format='json')
    parsed = json.loads(serialized)
    assert isinstance(parsed, dict)


def test_serialize_yaml():
    """Report serializes to valid YAML."""
    from logminer.reporter import build_report, serialize_report
    from logminer.parser import ErrorRecord
    import yaml

    report = build_report(
        [ErrorRecord(step_name='s', error_type='e', message='m')],
        [],
    )
    serialized = serialize_report(report, format='yaml')
    parsed = yaml.safe_load(serialized)
    assert isinstance(parsed, dict)
