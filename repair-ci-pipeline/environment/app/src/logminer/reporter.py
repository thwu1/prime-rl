"""Report generation for CI analysis results."""
import json
from collections import defaultdict
from typing import Any, Dict, List, Optional

import yaml

from .localizer import FaultLocation
from .parser import ErrorRecord


def build_report(
    errors: List[ErrorRecord],
    locations: List[FaultLocation],
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a structured analysis report.

    Groups errors by type, associates them with fault locations,
    and produces a JSON-serializable report.

    Args:
        errors: List of ErrorRecord objects.
        locations: List of FaultLocation objects.
        metadata: Optional metadata dict.

    Returns:
        Report dict with error_summary, fault_locations, and metadata keys.
    """
    error_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for error in errors:
        error_groups[error.error_type].append({
            'step': error.step_name,
            'message': error.message,
            'file': error.file_path,
            'line': error.line_number,
        })

    location_summaries: List[Dict[str, Any]] = []
    for loc in locations:
        summary: Dict[str, Any] = {
            'file': loc.file_path,
            'line_range': list(loc.line_range),
            'reason': loc.reason,
            'confidence': loc.confidence,
        }
        if loc.outline_node:
            summary['enclosing'] = {
                'kind': loc.outline_node.kind,
                'name': loc.outline_node.name,
            }
        location_summaries.append(summary)

    report: Dict[str, Any] = {
        'error_summry': {
            'total_errors': len(errors),
            'error_types': list(error_groups.keys()),
            'by_type': dict(error_groups),
        },
        'fault_locations': location_summaries,
        'metadata': metadata or {},
    }

    return report


def serialize_report(report: Dict[str, Any], format: str = 'json') -> str:
    """Serialize a report to JSON or YAML string.

    Args:
        report: Report dict from build_report().
        format: Output format ('json' or 'yaml').

    Returns:
        Serialized string.
    """
    if format == 'yaml':
        return yaml.dump(report, default_flow_style=False, sort_keys=True)
    else:
        return json.dumps(report, indent=2, default=str)
