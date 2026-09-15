"""Contamination detection for benchmark evaluation."""
from datetime import datetime


def parse_date(date_str: str) -> datetime:
    """Parse a date string in YYYY-MM-DD format."""
    return datetime.strptime(date_str, "%Y-%m-%d")


def is_contaminated(task_created_at: str, model_release_date: str) -> bool:
    """Check if a task-model pair is potentially contaminated.

    A task is potentially contaminated for a model if the task was created
    before the model was released, since the task data could have appeared
    in the model's training corpus.

    Args:
        task_created_at: task creation date (YYYY-MM-DD)
        model_release_date: model release date (YYYY-MM-DD)

    Returns:
        True if potentially contaminated
    """
    task_date = parse_date(task_created_at)
    release_date = parse_date(model_release_date)
    return task_date > release_date


def get_decontaminated_tasks(tasks, model_release_date: str):
    """Get list of task IDs that are not contaminated for a given model.

    Args:
        tasks: list of task dicts with 'task_id' and 'created_at'
        model_release_date: model release date (YYYY-MM-DD)

    Returns:
        list of non-contaminated task IDs
    """
    return [
        t["task_id"] for t in tasks
        if not is_contaminated(t["created_at"], model_release_date)
    ]
