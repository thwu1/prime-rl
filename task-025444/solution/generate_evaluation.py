#!/usr/bin/env python3
"""Generate forensic evaluation comparing reference_scorecard.json against
the correct scorecard output.

The reference scorecard was produced by an analyst who used exact string
equality for CWE prefix matching instead of startsWith(). This causes
the CWE 327->328 exception to not apply for "AppScanLike" (because
"AppScanLike" != "AppScan"), resulting in incorrect hash category values
and cascading overall metric and ranking errors.
"""
import json


def main():
    with open("/app/reference_scorecard.json") as f:
        reference = json.load(f)

    with open("/app/output/scorecard.json") as f:
        correct = json.load(f)

    def get_tool(scorecard, name):
        for tool in scorecard["tools"]:
            if tool["name"] == name:
                return tool
        return None

    discrepancies = []
    correct_tools = []
    incorrect_tools = []

    for ref_tool in reference["tools"]:
        tool_name = ref_tool["name"]
        cor_tool = get_tool(correct, tool_name)

        tool_has_errors = False

        # Compare category-level integer counts
        for cat_name in ref_tool["categories"]:
            ref_cat = ref_tool["categories"][cat_name]
            cor_cat = cor_tool["categories"][cat_name]

            for field in ["tp", "fn", "fp", "tn"]:
                if ref_cat[field] != cor_cat[field]:
                    discrepancies.append({
                        "tool": tool_name,
                        "category": cat_name,
                        "field": field,
                        "reference_value": ref_cat[field],
                        "correct_value": cor_cat[field],
                    })
                    tool_has_errors = True

        # Compare overall metrics (with tolerance for floating point)
        for field in ["macro_tpr", "macro_fpr", "youdens_j"]:
            ref_val = ref_tool["overall"][field]
            cor_val = cor_tool["overall"][field]
            if abs(ref_val - cor_val) > 0.001:
                discrepancies.append({
                    "tool": tool_name,
                    "category": "overall",
                    "field": field,
                    "reference_value": ref_val,
                    "correct_value": round(cor_val, 4),
                })
                tool_has_errors = True

        if tool_has_errors:
            incorrect_tools.append(tool_name)
        else:
            correct_tools.append(tool_name)

    evaluation = {
        "incorrect_tools": incorrect_tools,
        "correct_tools": correct_tools,
        "discrepancies": discrepancies,
        "root_cause": (
            "CWE exception prefix matching used exact string equality "
            "(tool_name == prefix) instead of startsWith(). The CWE 327->328 "
            "exception specifies tool_prefixes=['AppScan'], but 'AppScanLike' != "
            "'AppScan' under exact equality, while 'AppScanLike'.startsWith('AppScan') "
            "is true. This caused all AppScanLike hash-category findings (CWE 327) "
            "to be treated as non-matching instead of being accepted as CWE 328, "
            "cascading into incorrect hash TP/FN/FP/TN counts, overall macro-averaged "
            "metrics, and ranking position."
        ),
    }

    with open("/app/output/evaluation.json", "w") as f:
        json.dump(evaluation, f, indent=2)

    print("Evaluation report generated at /app/output/evaluation.json")


if __name__ == "__main__":
    main()
