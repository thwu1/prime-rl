
"""
Kernel crash report analysis and evaluation pipeline.

Implements:
  - parse_crash_report: multi-format kernel crash report parser
  - deduplicate_crashes: weighted Jaccard similarity grouping
  - evaluate_trials: kBench multi-trial resolution evaluator
  - compute_localization: patch-based localization metrics
"""

import re
import json
import os


def parse_crash_report(filepath):
    """Parse a kernel crash report file into structured data.

    Handles KASAN (slab-use-after-free, slab-out-of-bounds),
    general protection fault, and WARNING formats.

    Args:
        filepath: Path to crash report text file.

    Returns:
        dict with keys: bug_type, access_type, access_size,
        faulting_function, call_trace, task_comm, task_pid, kernel_version.
    """
    with open(filepath, 'r') as f:
        text = f.read()

    result = {
        'bug_type': None,
        'access_type': None,
        'access_size': None,
        'faulting_function': None,
        'call_trace': [],
        'task_comm': None,
        'task_pid': None,
        'kernel_version': None,
    }

    # --- Detect format and extract type-specific fields ---

    if 'BUG: KASAN:' in text:
        # KASAN format: BUG: KASAN: <type> in <function>+<offset>/<size>
        m = re.search(r'BUG: KASAN:\s+(\S+)\s+in\s+(\w+)\+', text)
        if m:
            result['bug_type'] = m.group(1)
            result['faulting_function'] = m.group(2)

        # Access info: Read/Write of size N at addr ...
        m = re.search(r'(Read|Write) of size (\d+) at addr', text)
        if m:
            result['access_type'] = m.group(1).lower()
            result['access_size'] = int(m.group(2))

    elif 'general protection fault' in text.lower():
        result['bug_type'] = 'general-protection-fault'
        # Faulting function from RIP line: RIP: XXXX:func+offset/size
        m = re.search(r'RIP:\s+\w+:(\w+)\+', text)
        if m:
            result['faulting_function'] = m.group(1)

    elif 'WARNING:' in text:
        result['bug_type'] = 'warning'
        # WARNING: CPU: N PID: N at file:line func+offset/size
        m = re.search(r'WARNING:.*\bat\s+\S+:\d+\s+(\w+)\+', text)
        if m:
            result['faulting_function'] = m.group(1)

    # --- Task info ---
    # Try "by task comm/pid" first (KASAN format)
    m = re.search(r'by task (\S+)/(\d+)', text)
    if m:
        result['task_comm'] = m.group(1)
        result['task_pid'] = int(m.group(2))
    else:
        # Fall back to "PID: N Comm: name" (GPF/WARNING format)
        m = re.search(r'PID:\s*(\d+)\s+Comm:\s*(\S+)', text)
        if m:
            result['task_pid'] = int(m.group(1))
            result['task_comm'] = m.group(2)

    # --- Kernel version ---
    # Version string is always followed by #N (build number)
    m = re.search(r'(\d+\.\d+\.\d+\S*)\s+#\d+', text)
    if m:
        result['kernel_version'] = m.group(1)

    # --- Call trace ---
    # Extract frames between <TASK> and </TASK> markers
    task_match = re.search(r'<TASK>(.*?)</TASK>', text, re.DOTALL)
    if task_match:
        task_block = task_match.group(1)
        # Match func+0xOFFSET/0xSIZE patterns
        frames = re.findall(
            r'(\w+)\+(0x[0-9a-fA-F]+)/(0x[0-9a-fA-F]+)',
            task_block
        )
        result['call_trace'] = [
            {'function': func, 'offset': offset, 'size': size}
            for func, offset, size in frames
        ]

    return result


def deduplicate_crashes(reports, top_n=5, threshold=0.7):
    """Group crash reports by weighted Jaccard similarity of call traces.

    Args:
        reports: dict mapping report_id -> parsed crash report dict.
        top_n: Number of top call trace frames to consider.
        threshold: Minimum similarity to group two reports.

    Returns:
        List of groups, each a sorted list of report IDs.
        Outer list sorted by first element of each group.
    """
    ids = sorted(reports.keys())
    n = len(ids)

    # Union-Find structure
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Compute pairwise similarities and merge above threshold
    for i in range(n):
        for j in range(i + 1, n):
            sim = _weighted_jaccard(reports[ids[i]], reports[ids[j]], top_n)
            if sim >= threshold:
                union(i, j)

    # Collect groups
    from collections import defaultdict
    groups_map = defaultdict(list)
    for i in range(n):
        groups_map[find(i)].append(ids[i])

    result = [sorted(g) for g in groups_map.values()]
    return sorted(result, key=lambda g: g[0])


def _weighted_jaccard(report_a, report_b, top_n):
    """Compute weighted Jaccard similarity between two crash reports.

    Weight of frame at 0-indexed position i is 1/(i+1).
    Similarity = sum(min(wA(f), wB(f))) / sum(max(wA(f), wB(f)))
    over all function names appearing in either trace's top-N.
    """
    trace_a = report_a.get('call_trace', [])[:top_n]
    trace_b = report_b.get('call_trace', [])[:top_n]

    # Map function name -> position (first occurrence)
    pos_a = {}
    for i, frame in enumerate(trace_a):
        fname = frame['function']
        if fname not in pos_a:
            pos_a[fname] = i

    pos_b = {}
    for i, frame in enumerate(trace_b):
        fname = frame['function']
        if fname not in pos_b:
            pos_b[fname] = i

    all_funcs = set(pos_a.keys()) | set(pos_b.keys())
    if not all_funcs:
        return 0.0

    numerator = 0.0
    denominator = 0.0

    for f in all_funcs:
        w_a = 1.0 / (pos_a[f] + 1) if f in pos_a else 0.0
        w_b = 1.0 / (pos_b[f] + 1) if f in pos_b else 0.0
        numerator += min(w_a, w_b)
        denominator += max(w_a, w_b)

    return numerator / denominator if denominator > 0 else 0.0


def evaluate_trials(receipt_paths, rerun_success=3, max_trys=5):
    """Implement the kBench multi-trial resolution evaluation protocol.

    Processes receipt files sequentially. First receipt seeds tracking;
    subsequent receipts only update bugs on the redo list.

    Args:
        receipt_paths: Ordered list of receipt JSON file paths.
        rerun_success: Number of "no crash reproduced" needed to resolve.
        max_trys: Maximum number of trial attempts per bug.

    Returns:
        dict with resolved (list), unresolved (list), resolution_count (int).
    """
    successful_bugs = {}
    redo = []
    first_run = True

    for receipt_path in receipt_paths:
        with open(receipt_path, 'r') as f:
            receipt = json.load(f)

        jobs = receipt['jobs']
        ans = []

        for job in jobs:
            bug_id = job['bug_id']

            # Split bug_id into cleaned_bug_id and K
            try:
                parts = bug_id.split('__')
                cleaned_bug_id, K = parts[0], parts[1]
            except (IndexError, ValueError):
                cleaned_bug_id, K = bug_id, '0'

            if not first_run:
                if bug_id not in redo:
                    continue

            # Extract execution results
            message = job['execution']['message']
            crash_description = None
            if message is None:
                crash_description = job['execution']['crash_description']

            try:
                if not first_run:
                    # Subsequent receipts: update existing trial dict
                    if (successful_bugs.get(cleaned_bug_id) and
                            successful_bugs[cleaned_bug_id].get(K)):
                        trial_dict = successful_bugs[cleaned_bug_id][K]
                        correct_key = _get_correct_key(trial_dict)
                        if correct_key is not None:
                            if message:
                                trial_dict[correct_key] = message.lower()
                            else:
                                trial_dict[correct_key] = crash_description

                            max_success = _reach_max_success(
                                trial_dict, rerun_success
                            )
                            max_attempts = _reach_max_attempts(trial_dict)

                            if (not max_success and
                                    not max_attempts and
                                    crash_description is None):
                                ans.append(bug_id)
                else:
                    # First receipt: seed tracking
                    if crash_description is not None:
                        continue
                    if message.lower() == 'no crash reproduced':
                        if cleaned_bug_id not in successful_bugs:
                            successful_bugs[cleaned_bug_id] = {}
                        trial_dict = {
                            i + 1: None for i in range(max_trys)
                        }
                        trial_dict[1] = message.lower()
                        successful_bugs[cleaned_bug_id][K] = trial_dict
                        ans.append(bug_id)
            except Exception:
                continue

        redo = ans
        first_run = False

    # Compute final results
    resolved = []
    unresolved = []

    for cleaned_bug_id, k_dict in successful_bugs.items():
        for K, trial_dict in k_dict.items():
            bug_id = '{}__{}' .format(cleaned_bug_id, K)
            if _reach_max_success(trial_dict, rerun_success):
                resolved.append(bug_id)
            else:
                unresolved.append(bug_id)

    return {
        'resolved': sorted(resolved),
        'unresolved': sorted(unresolved),
        'resolution_count': len(resolved),
    }


def _get_correct_key(trial_dict):
    """Return the first trial slot that is still None."""
    for key in sorted(trial_dict.keys()):
        if trial_dict[key] is None:
            return key
    return None


def _reach_max_success(trial_dict, rerun_success):
    """Check if total 'no crash reproduced' count >= rerun_success."""
    counter = 0
    for key in sorted(trial_dict.keys()):
        if trial_dict[key] == 'no crash reproduced':
            counter += 1
            if counter == rerun_success:
                return True
    return False


def _reach_max_attempts(trial_dict):
    """Check if all trial slots are filled."""
    for key in sorted(trial_dict.keys()):
        if trial_dict[key] is None:
            return False
    return True


def compute_localization(patch_path, ranked_files):
    """Compute localization metrics from a unified diff and ranked file list.

    Args:
        patch_path: Path to unified diff file.
        ranked_files: Ordered list of predicted file paths.

    Returns:
        dict with ground_truth_files, precision_at_{1,3,5},
        recall_at_{1,3,5}, file_iou.
    """
    with open(patch_path, 'r') as f:
        patch_text = f.read()

    # Parse unified diff to extract modified file paths
    ground_truth = set()
    for line in patch_text.split('\n'):
        m = re.match(r'^diff --git a/(\S+) b/\S+', line)
        if m:
            ground_truth.add(m.group(1))

    gt_list = sorted(ground_truth)

    result = {
        'ground_truth_files': gt_list,
    }

    # Precision@K and Recall@K
    for k in [1, 3, 5]:
        top_k = set(ranked_files[:k])
        intersection = ground_truth & top_k
        if k <= len(ranked_files):
            precision = len(intersection) / k
        else:
            precision = len(intersection) / max(len(ranked_files), 1)
        recall = (
            len(intersection) / len(ground_truth) if ground_truth else 0.0
        )
        result['precision_at_{}'.format(k)] = precision
        result['recall_at_{}'.format(k)] = recall

    # File IoU using all ranked files
    all_ranked = set(ranked_files)
    union = ground_truth | all_ranked
    intersection = ground_truth & all_ranked
    result['file_iou'] = len(intersection) / len(union) if union else 0.0

    return result
