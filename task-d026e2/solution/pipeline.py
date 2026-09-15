"""
End-to-end pipeline for generalization-aware kernel evaluation.

Reads task manifest, applies injections, reads pre-computed evaluation
results, classifies generalization outcomes, and produces a summary YAML.
"""
import os
import shutil
import yaml

from .injection import apply_injection
from .scoring import score as calc_score, resolve_speedup_ratio
from .analysis import classify_generalization, compute_summary


def _read_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _write_yaml(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _apply_injections_to_workspace(data_dir, task_entry, output_dir):
    """
    Copy workspace files and apply held-out shape injections.

    Returns the path to the injected workspace.
    """
    task_id = task_entry['id']
    ws_dir = os.path.join(data_dir, task_entry['workspace_dir'])
    config_path = os.path.join(data_dir, task_entry['held_out_config'])

    # Create injected workspace copy
    injected_ws = os.path.join(output_dir, 'injected', task_id)
    if os.path.exists(injected_ws):
        shutil.rmtree(injected_ws)
    shutil.copytree(ws_dir, injected_ws)

    # Read held-out config
    config = _read_yaml(config_path)

    # Apply each injection
    for inj_spec in config.get('injections', []):
        target_file = os.path.join(injected_ws, inj_spec['file'])
        if not os.path.exists(target_file):
            continue
        with open(target_file) as f:
            source = f.read()
        modified = apply_injection(source, inj_spec)
        with open(target_file, 'w') as f:
            f.write(modified)

    return injected_ws


def _process_task(data_dir, task_entry, output_dir):
    """
    Process a single task: apply injections, read results, classify, score.

    Returns a per-task result dict.
    """
    task_name = task_entry['name']

    # Apply injections
    _apply_injections_to_workspace(data_dir, task_entry, output_dir)

    # Read evaluation results
    orig_result = _read_yaml(os.path.join(data_dir, task_entry['eval_orig']))
    opt_result = _read_yaml(os.path.join(data_dir, task_entry['eval_opt']))
    original_run = _read_yaml(os.path.join(data_dir, task_entry['original_run']))

    # Extract correctness
    orig_correct = orig_result.get('pass_correctness', False)
    opt_correct = opt_result.get('pass_correctness', False)
    opt_comp = opt_result.get('pass_compilation', False)

    # Classify generalization
    status = classify_generalization(orig_correct, opt_correct)

    # Compute speedup for held-out evaluation
    orig_time = orig_result.get('execution_time_ms', 0.0)
    opt_time = opt_result.get('execution_time_ms', 0.0)

    heldout_speedup = 0.0
    if status == 'both_pass' and orig_time > 0 and opt_time > 0:
        heldout_speedup = orig_time / opt_time

    # Compute heldout score
    heldout_score = calc_score(
        opt_comp,
        opt_correct,
        orig_time,
        opt_time,
        heldout_speedup,
    )

    return {
        'task_name': task_name,
        'generalization_status': status,
        'orig_heldout_pass_correctness': orig_correct,
        'opt_pass_correctness': opt_correct,
        'heldout_speedup': heldout_speedup,
        'original_run_speedup': original_run.get('speedup_ratio', 0.0),
        'heldout_score': heldout_score,
        'original_run_score': original_run.get('score', 0.0),
    }


def run_pipeline(data_dir, output_dir):
    """
    Run the complete generalization evaluation pipeline.

    Args:
        data_dir: Path to /app/data/ with manifest and all input data
        output_dir: Path to write outputs (injected files, summary YAML)

    Returns:
        Summary dict (also written to output_dir/heldout_summary.yaml)
    """
    os.makedirs(output_dir, exist_ok=True)

    # Read manifest
    manifest = _read_yaml(os.path.join(data_dir, 'task_manifest.yaml'))
    tasks = manifest.get('tasks', [])

    # Process each task
    task_results = []
    for task_entry in tasks:
        result = _process_task(data_dir, task_entry, output_dir)
        task_results.append(result)

    # Compute summary
    summary = compute_summary(task_results)

    # Write summary YAML
    _write_yaml(os.path.join(output_dir, 'heldout_summary.yaml'), summary)

    return summary
