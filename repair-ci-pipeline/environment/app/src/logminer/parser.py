"""CI log parser - extracts structured error records from raw CI log output."""
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, OrderedDict


@dataclass
class ErrorRecord:
    """Represents a single error extracted from CI logs."""
    step_name: str
    error_type: str
    message: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    column: Optional[int] = None
    raw_text: str = ""


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return re.sub(r'\x1b\[\d+m', '', text)


def parse_step_header(line: str) -> Optional[str]:
    """Extract CI step name from a log header line."""
    match = re.match(r'^##\[group\](.*)', line)
    if match:
        return match.group(1).strip()
    match = re.match(r'^=+\s+(.+?)\s+=+$', line)
    if match:
        return match.group(1).strip()
    return None


ERROR_PATTERNS: Dict[str, "re.Pattern[str]"] = {
    'pytest': re.compile(
        r'^(?:FAILED|ERROR)\s+(.+?)(?:::(\w+))?\s*-\s*(.+)$',
        re.MULTILINE,
    ),
    'mypy': re.compile(
        r'^(.+?):(\d+):\s*error:\s*(.+?)(?:\s+\[(.+?)\])?$',
        re.MULTILINE,
    ),
    'ruff': re.compile(
        r'^(.+?):(\d+):(\d+):\s*((?:E|W|F|I|N|D|UP|B|A|C4|SIM|TCH|RUF)\d+)\s+(.+)$',
        re.MULTILINE,
    ),
    'pip': re.compile(
        r'(?:ERROR|error):\s*(?:Could not find a version|No matching distribution|'
        r'ResolutionImpossible).*$',
        re.MULTILINE,
    ),
}


def extract_error_blocks(log_text: str, step_name: str = "unknown") -> List[ErrorRecord]:
    """Extract structured error records from a CI log section.

    Args:
        log_text: Raw log text (may contain ANSI escape codes).
        step_name: Name of the CI step this log came from.

    Returns:
        List of ErrorRecord objects.
    """
    cleaned = strip_ansi(log_text)
    errors: List[ErrorRecord] = []

    for error_type, pattern in ERROR_PATTERNS.items():
        for match in pattern.finditer(cleaned):
            if error_type == 'pytest':
                record = ErrorRecord(
                    step_name=step_name,
                    error_type='test_failure',
                    message=match.group(3),
                    file_path=match.group(1),
                    raw_text=match.group(0),
                )
            elif error_type == 'mypy':
                record = ErrorRecord(
                    step_name=step_name,
                    error_type='type_error',
                    message=match.group(3),
                    file_path=match.group(1),
                    line_number=int(match.group(2)),
                    raw_text=match.group(0),
                )
            elif error_type == 'ruff':
                record = ErrorRecord(
                    step_name=step_name,
                    error_type='lint_error',
                    message=f"{match.group(4)} {match.group(5)}",
                    file_path=match.group(1),
                    line_number=int(match.group(2)),
                    column=int(match.group(3)),
                    raw_text=match.group(0),
                )
            elif error_type == 'pip':
                record = ErrorRecord(
                    step_name=step_name,
                    error_type='dependency_error',
                    message=match.group(0),
                    raw_text=match.group(0),
                )
            else:
                continue
            errors.append(record)

    return errors


def parse_full_log(log_text: str) -> Dict[str, List[ErrorRecord]]:
    """Parse a complete CI log into step-grouped error records.

    Returns:
        Dict mapping step names to lists of ErrorRecord objects.
    """
    cleaned = strip_ansi(log_text)
    lines = cleaned.split('\n')

    steps: Dict[str, List[str]] = {}
    current_step = "pre-run"
    current_lines: List[str] = []

    for line in lines:
        header = parse_step_header(line)
        if header:
            if current_lines:
                steps[current_step] = current_lines
            current_step = header
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        steps[current_step] = current_lines

    result: Dict[str, List[ErrorRecord]] = {}
    for step_name, step_lines in steps.items():
        step_text = '\n'.join(step_lines)
        errors = extract_error_blocks(step_text, step_name)
        if errors:
            result[step_name] = errors

    return result
