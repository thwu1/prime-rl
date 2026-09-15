"""
Patch analysis against KASAN crash reports.

Parses unified diff patches, identifies the patch strategy (bounds check,
null check, refcount fix, etc.), and determines whether the patch
appropriately targets the localized bug.
"""

import re
import os
from dataclasses import dataclass, field
from typing import List, Tuple
from .parser import KASANReport


@dataclass
class PatchAnalysis:
    """Result of analyzing a patch against a crash report."""
    target_files: List[str] = field(default_factory=list)
    target_functions: List[str] = field(default_factory=list)
    patch_strategy: str = "other"
    targets_buggy_file: bool = False
    targets_buggy_function: bool = False
    strategy_matches_bug: bool = False
    classification: str = "wrong"
    applies_cleanly: bool = False


# Maps bug types to appropriate patch strategies
BUG_STRATEGY_MAP = {
    "slab-out-of-bounds": {"bounds_check", "input_validation", "size_fix"},
    "global-out-of-bounds": {"bounds_check", "input_validation", "size_fix"},
    "stack-out-of-bounds": {"bounds_check", "input_validation", "size_fix"},
    "vmalloc-out-of-bounds": {"bounds_check", "input_validation", "size_fix"},
    "slab-use-after-free": {"refcount", "locking", "lifetime_fix", "null_check"},
    "use-after-free": {"refcount", "locking", "lifetime_fix", "null_check"},
    "null-ptr-deref": {"null_check", "error_handling", "initialization"},
    "invalid-free": {"refcount", "locking", "lifetime_fix"},
    "wild-memory-access": {"bounds_check", "null_check", "initialization"},
}

# Patterns that indicate specific patch strategies
STRATEGY_PATTERNS = {
    "bounds_check": [
        r'if\s*\(.+\s*[<>]=?\s*.+(?:length|len|size|count|num|actual_length)',
        r'if\s*\(.+(?:length|len|size|count|num|actual_length)\s*[<>]=?\s*',
        r'min\s*\(', r'min_t\s*\(',
        r'clamp\s*\(', r'clamp_t\s*\(',
        r'if\s*\(\s*\w+\s*>=?\s*\w+_(?:size|len|max|limit)',
        r'if\s*\(\s*\w+\s*<\s*\d+\s*\)',
    ],
    "null_check": [
        r'if\s*\(\s*!\s*\w+\s*\)',
        r'if\s*\(\s*\w+\s*==\s*NULL\s*\)',
        r'!\w+\s*->\s*\w+',
        r'!\w+\s*\|\|\s*!\w+',
        r'IS_ERR_OR_NULL\s*\(',
    ],
    "refcount": [
        r'(?:atomic|refcount|kref)_(?:inc|dec|get|put|set)',
        r'rcu_(?:read_lock|read_unlock|dereference)',
        r'spin_lock', r'mutex_lock', r'down_read', r'down_write',
    ],
    "locking": [
        r'spin_lock', r'spin_unlock',
        r'mutex_lock', r'mutex_unlock',
        r'read_lock', r'write_lock',
        r'rcu_read_lock', r'rcu_read_unlock',
        r'synchronize_rcu',
    ],
    "input_validation": [
        r'if\s*\(.+\s*[<>]=?\s*.+(?:length|len|size|count|actual_length)',
        r'if\s*\(\s*\w+\s*<\s*\d+\s*\)',
        r'dev_warn\s*\(', r'dev_err\s*\(',
        r'pr_warn\s*\(', r'pr_err\s*\(',
    ],
    "error_handling": [
        r'if\s*\(\s*IS_ERR\s*\(',
        r'if\s*\(\s*err\s*\)',
        r'if\s*\(\s*ret\s*[<!=]',
        r'goto\s+\w+err',
    ],
}


def _extract_patch_files(patch_text: str) -> List[str]:
    """Extract file paths from unified diff headers."""
    files = []
    for m in re.finditer(r'^(?:---|\+\+\+)\s+[ab]/(.+)$', patch_text, re.MULTILINE):
        path = m.group(1).strip()
        if path and path not in files and path != '/dev/null':
            files.append(path)
    return files


def _extract_patch_functions(patch_text: str) -> List[str]:
    """Extract function names from diff hunk headers (@@ ... @@ function)."""
    functions = []
    for m in re.finditer(r'^@@\s+[^@]+@@\s+.*?(\w+)\s*\(', patch_text, re.MULTILINE):
        func = m.group(1)
        if func and func not in functions:
            functions.append(func)
    return functions


def _detect_strategy(patch_text: str) -> str:
    """Detect the patch strategy from added lines."""
    # Extract only added lines (+ prefix but not +++ header)
    added_lines = []
    for line in patch_text.split('\n'):
        if line.startswith('+') and not line.startswith('+++'):
            added_lines.append(line[1:])
    added_text = '\n'.join(added_lines)

    if not added_text.strip():
        return "other"

    # Score each strategy
    scores = {}
    for strategy, patterns in STRATEGY_PATTERNS.items():
        score = 0
        for pattern in patterns:
            matches = re.findall(pattern, added_text, re.IGNORECASE)
            score += len(matches)
        if score > 0:
            scores[strategy] = score

    if not scores:
        return "other"

    return max(scores, key=scores.get)


def _file_matches(patch_file: str, report_file: str) -> bool:
    """Check if a patch file path matches a report source file path."""
    # Normalize paths for comparison
    pf = patch_file.strip().rstrip('/')
    rf = report_file.strip().rstrip('/')

    # Exact match
    if pf == rf:
        return True

    # Check if one ends with the other (handles relative vs absolute)
    if pf.endswith(rf) or rf.endswith(pf):
        return True

    # Check basename match with same directory context
    pf_parts = pf.split('/')
    rf_parts = rf.split('/')
    if pf_parts[-1] == rf_parts[-1] and len(pf_parts) >= 2 and len(rf_parts) >= 2:
        if pf_parts[-2] == rf_parts[-2]:
            return True

    return False


def _context_matches_file(patch_text: str, file_path: str) -> bool:
    """Check if patch context lines match content in a file (Python-based)."""
    try:
        with open(file_path) as f:
            source_lines = f.read().split('\n')
    except (IOError, OSError):
        return False

    # Parse hunks from the patch
    hunk_pattern = re.compile(r'^@@\s+[^@]+@@', re.MULTILINE)
    hunk_starts = [m.start() for m in hunk_pattern.finditer(patch_text)]
    if not hunk_starts:
        return False

    for hi, hunk_start in enumerate(hunk_starts):
        hunk_end = hunk_starts[hi + 1] if hi + 1 < len(hunk_starts) else len(patch_text)
        hunk_text = patch_text[hunk_start:hunk_end]
        hunk_lines = hunk_text.split('\n')[1:]  # Skip @@ header

        # Remove trailing empty elements from the split
        while hunk_lines and hunk_lines[-1] == '':
            hunk_lines = hunk_lines[:-1]

        # Extract context and removed lines (what should be in the original file)
        # Bare empty lines in diffs represent empty lines in the source
        original_lines = []
        for line in hunk_lines:
            if line.startswith(' '):
                original_lines.append(line[1:])
            elif line.startswith('-'):
                original_lines.append(line[1:])
            elif line.startswith('+'):
                pass  # Added lines are not in the original
            elif line == '':
                # Bare empty line = context line for empty source line
                original_lines.append('')

        if not original_lines:
            continue

        # Search for the context in the source file
        found = False
        for start in range(len(source_lines)):
            if source_lines[start] == original_lines[0]:
                # Check if all original lines match consecutively
                if start + len(original_lines) > len(source_lines):
                    continue
                match = True
                for j, orig_line in enumerate(original_lines):
                    if source_lines[start + j] != orig_line:
                        match = False
                        break
                if match:
                    found = True
                    break

        if not found:
            return False

    return True


def _check_applies_cleanly(patch_text: str, kernel_src_dir: str = "/app/kernel_src") -> bool:
    """Check if a patch applies cleanly to kernel source excerpts."""
    if not os.path.isdir(kernel_src_dir):
        return False

    # Extract target file from patch
    files = re.findall(r'^\+\+\+\s+[ab]/(.+)$', patch_text, re.MULTILINE)
    if not files:
        return False

    target_file = os.path.join(kernel_src_dir, files[0].strip())
    if not os.path.isfile(target_file):
        return False

    # Use Python-based context matching (works reliably with excerpt files
    # that have different line numbers than the original kernel source)
    return _context_matches_file(patch_text, target_file)


def analyze_patch(
    patch_text: str,
    report: KASANReport,
    buggy_functions: List[Tuple[str, str, int, float]]
) -> PatchAnalysis:
    """
    Analyze a unified diff patch against a KASAN crash report.

    Args:
        patch_text: The patch in unified diff format
        report: Parsed KASAN report
        buggy_functions: Localization results from localize_bug()

    Returns:
        PatchAnalysis with classification result
    """
    analysis = PatchAnalysis()

    # Extract patch targets
    analysis.target_files = _extract_patch_files(patch_text)
    analysis.target_functions = _extract_patch_functions(patch_text)

    # Check if patch targets the buggy file
    buggy_files = set()
    buggy_files.add(report.source_file)
    for func, src, line, conf in buggy_functions:
        if src:
            buggy_files.add(src)

    for patch_file in analysis.target_files:
        for buggy_file in buggy_files:
            if _file_matches(patch_file, buggy_file):
                analysis.targets_buggy_file = True
                break

    # Check if patch targets a buggy function
    buggy_func_names = {f[0] for f in buggy_functions}
    buggy_func_names.add(report.faulting_function)
    for pf in analysis.target_functions:
        if pf in buggy_func_names:
            analysis.targets_buggy_function = True
            break

    # Detect patch strategy
    analysis.patch_strategy = _detect_strategy(patch_text)

    # Check if strategy matches bug type
    matching_strategies = BUG_STRATEGY_MAP.get(report.bug_type, set())
    analysis.strategy_matches_bug = analysis.patch_strategy in matching_strategies

    # Classify the patch
    if analysis.targets_buggy_file and analysis.strategy_matches_bug:
        analysis.classification = "plausible"
    elif analysis.targets_buggy_file and not analysis.strategy_matches_bug:
        analysis.classification = "helpful"
    else:
        analysis.classification = "wrong"

    # Check patch applicability against kernel source
    analysis.applies_cleanly = _check_applies_cleanly(patch_text)

    return analysis
