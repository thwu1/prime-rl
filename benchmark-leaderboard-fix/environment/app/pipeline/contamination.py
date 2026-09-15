"""Data contamination detection for benchmark evaluation.

See /app/docs/methodology.md section 4 for the contamination definition.
"""


def is_contaminated(task_created_at, model_release_date):
    """Determine if a task-model pair is potentially contaminated."""
    raise NotImplementedError


def get_clean_task_ids(tasks, model_release_date):
    """Return task IDs that are not contaminated for the given model."""
    raise NotImplementedError
