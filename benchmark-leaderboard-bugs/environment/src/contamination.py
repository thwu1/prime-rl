"""Contamination detection for benchmark evaluation."""


def is_contaminated(task_created_at, model_release_date):
    """Check if a task is potentially contaminated for a given model.

    A task is contaminated if it was created before the model's release date.
    """
    return task_created_at <= model_release_date


def count_contaminated_tasks(tasks, model_release_date):
    """Count tasks potentially contaminated for a model."""
    return sum(
        1 for t in tasks if is_contaminated(t["created_at"], model_release_date)
    )
