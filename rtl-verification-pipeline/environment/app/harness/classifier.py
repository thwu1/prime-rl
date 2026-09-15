"""Fail-to-pass classification logic."""


def classify_case(pre_patch_result, post_patch_result):
    """Classify a test case based on pre-patch and post-patch results.

    The fail-to-pass (f2p) paradigm:
    - A case is "resolved" if the test FAILS before the fix and PASSES after.
    - A case is "regression" if the test PASSES before and FAILS after.
    - A case is "persistent_fail" if it fails both before and after.
    - A case is "already_passing" if it passes both before and after.

    Args:
        pre_patch_result: dict from parser.parse_simulation_log (before fix)
        post_patch_result: dict from parser.parse_simulation_log (after fix)

    Returns:
        str: Classification label
    """
    pre_status = pre_patch_result["overall_status"]
    post_status = post_patch_result["overall_status"]

    if pre_status == "PASS" and post_status == "FAIL":
        return "resolved"
    elif pre_status == "FAIL" and post_status == "PASS":
        return "regression"
    elif pre_status == "FAIL" and post_status == "FAIL":
        return "persistent_fail"
    elif pre_status == "PASS" and post_status == "PASS":
        return "already_passing"
    else:
        return "inconclusive"
