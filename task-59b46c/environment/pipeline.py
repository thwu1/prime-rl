"""Cross-subject EEG motor imagery decoding pipeline.

Implement the decode function below. You may add any helper functions,
classes, or imports you need.
"""

import numpy as np
from typing import Dict, List


def decode(dataset_params: dict) -> dict:
    """Perform leave-one-subject-out cross-subject EEG motor imagery decoding.

    Generates the dataset using eeg_data.generate_dataset(**dataset_params),
    then evaluates cross-subject decoding performance where each subject is
    held out once as the test set while the remaining subjects form the
    training set.

    Args:
        dataset_params: Keyword arguments for eeg_data.generate_dataset().

    Returns:
        dict with keys:
            'accuracies': list of float, per-subject classification accuracy
            'mean_accuracy': float, mean across all subjects
            'predictions': list of np.ndarray, per-subject predicted labels
    """
    raise NotImplementedError
