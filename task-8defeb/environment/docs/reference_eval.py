"""
Reference evaluation utilities from a prior ISLES challenge edition.

NOTE: This script depends on the 'panoptica' library and uses IoU-threshold
matching for lesion instance detection. The current ISLES-26 evaluation protocol
uses a different (simpler) lesion detection criterion. See evaluation_protocol.md
for the authoritative specification.

This file is provided for background context only.
"""

__author__ = "Ezequiel de la Rosa"

import numpy as np
import warnings
from panoptica import (
    InputType,
    Panoptica_Evaluator,
    ConnectedComponentsInstanceApproximator,
    NaiveThresholdMatching,
)


def compute_absolute_volume_difference(im1, im2, voxel_size):
    """
    Computes the absolute volume difference between two masks.

    Parameters
    ----------
    im1 : array-like, bool
        Any array of arbitrary size. If not boolean, will be converted.
    im2 : array-like, bool
        Any other array of identical size. If not boolean, it will be converted.
    voxel_size : scalar, float (ml)
        If not float, it will be converted.

    Returns
    -------
    abs_vol_diff : float, measured in ml.
        Absolute volume difference as a float.
        Maximum similarity = 0
        No similarity = inf
    """

    im1 = np.asarray(im1).astype(bool)
    im2 = np.asarray(im2).astype(bool)
    voxel_size = voxel_size.astype(float)

    if im1.shape != im2.shape:
        warnings.warn(
            "Shape mismatch: ground_truth and prediction have difference shapes."
            " The absolute volume difference is computed with mismatching shape masks"
        )

    ground_truth_volume = np.sum(im1) * voxel_size
    prediction_volume = np.sum(im2) * voxel_size
    abs_vol_diff = np.abs(ground_truth_volume - prediction_volume)

    return abs_vol_diff


def compute_dice_f1_instance_difference(ground_truth, prediction, empty_value=1.0):
    """
    Computes the lesion-wise F1-score, instance count difference, and Dice score
    between two masks using panoptica with IoU-threshold matching.

    Parameters
    ----------
    ground_truth : array-like, int
        Any array of arbitrary size. If not int, it will be converted.
    prediction: array-like, int
        Any other array of identical size. If not int, it will be converted.
    empty_value : scalar, float.

    Returns
    -------
    f1_score : float
        Instance-wise F1-score as float. Max = 1, Min = 0.
        If both images are empty: F1 = empty_value
    dice_score : float
        Dice coefficient as a float on range [0,1].
        If both images are empty: dice = empty_value
    instance_count_difference : int
        Absolute instance count difference as integer.
    """

    ground_truth = np.asarray(ground_truth).astype(int)
    prediction = np.asarray(prediction).astype(int)

    evaluator = Panoptica_Evaluator(
        expected_input=InputType.SEMANTIC,
        instance_approximator=ConnectedComponentsInstanceApproximator(),
        instance_matcher=NaiveThresholdMatching(matching_threshold=0.2),
    )

    result, _ = evaluator.evaluate(prediction, ground_truth, verbose=False)["ungrouped"]

    instance_count_difference = abs(result.num_ref_instances - result.num_pred_instances)

    if result.num_ref_instances == 0 and result.num_pred_instances == 0:
        f1_score = empty_value
        dice_score = empty_value
    else:
        f1_score = result.rq
        dice_score = result.global_bin_dsc

    return f1_score, instance_count_difference, dice_score
