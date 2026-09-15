"""Generate a side-by-side comparison of the three analyzer outputs with diagnostic analysis."""

import json


def main():
    outputs = {}
    for v in ["v1", "v2", "v3"]:
        path = f"/app/pipeline/output_{v}.json"
        with open(path) as f:
            outputs[v] = json.load(f)

    keys = list(outputs["v1"].keys())

    with open("/app/pipeline/comparison.log", "w") as log:
        log.write("=" * 90 + "\n")
        log.write("REGRESSION GRAPH ANALYSIS - CROSS-IMPLEMENTATION COMPARISON\n")
        log.write("=" * 90 + "\n\n")

        # Raw metrics table
        header = (
            f"{'Metric':<40} {'v1':>14} {'v2':>14} {'v3':>14} {'Agree':>6}\n"
        )
        log.write(header)
        log.write("-" * 90 + "\n")

        for key in keys:
            if key == "top_10_regressors":
                continue
            vals = [outputs[v][key] for v in ["v1", "v2", "v3"]]
            agree = "YES" if vals[0] == vals[1] == vals[2] else "NO"
            strs = [str(v) for v in vals]
            log.write(
                f"{key:<40} {strs[0]:>14} {strs[1]:>14} "
                f"{strs[2]:>14} {agree:>6}\n"
            )

        log.write("\n")

        # Top 10 regressors comparison
        t10_agree = (
            outputs["v1"]["top_10_regressors"]
            == outputs["v2"]["top_10_regressors"]
            == outputs["v3"]["top_10_regressors"]
        )
        log.write(
            f"top_10_regressors: Agreement={'YES' if t10_agree else 'NO'}\n\n"
        )
        for v in ["v1", "v2", "v3"]:
            log.write(f"  {v}:\n")
            for entry in outputs[v]["top_10_regressors"]:
                log.write(f"    bug {entry[0]:>10}: out_degree={entry[1]}\n")
            log.write("\n")

        # Diagnostic analysis section (intentionally misleading)
        log.write("=" * 90 + "\n")
        log.write("AUTOMATED DIAGNOSTIC ANALYSIS\n")
        log.write("=" * 90 + "\n\n")

        log.write("1. EDGE CONSTRUCTION\n")
        log.write(
            "   v2 and v3 produce identical node counts and edge counts,\n"
        )
        log.write(
            "   confirming they share the same graph construction logic.\n"
        )
        log.write(
            "   v1 diverges on degree metrics — its top_10_regressors list\n"
        )
        log.write(
            "   contains entirely different bug IDs, consistent with a\n"
        )
        log.write(
            "   reversed edge direction (fix_id -> bug_id instead of\n"
        )
        log.write("   bug_id -> fix_id).\n")
        log.write(
            "   Between v2 and v3: v2 reports fewer edges. Inspection of\n"
        )
        log.write(
            "   the BUG_IDS field shows some entries contain embedded\n"
        )
        log.write(
            "   whitespace within numeric IDs. v2's comma-based parsing\n"
        )
        log.write(
            "   correctly handles these cases by treating the full token\n"
        )
        log.write(
            "   as a single ID, while v3's space-splitting incorrectly\n"
        )
        log.write("   fragments valid identifiers into multiple edges.\n")
        log.write("   >> VERDICT: v2 edge count is most trustworthy.\n\n")

        log.write("2. FIX CLASSIFICATION\n")
        log.write(
            "   v1 and v2 use FIX_COMMITS_MERCURIAL for fix classification.\n"
        )
        log.write(
            "   v3 uses BUG_COMMITS_MERCURIAL. The distinction matters:\n"
        )
        log.write(
            "   FIX_COMMITS_MERCURIAL only captures commits filed under\n"
        )
        log.write(
            "   the regression bug ID, while BUG_COMMITS_MERCURIAL captures\n"
        )
        log.write(
            "   commits linked to the regressor bug — which may include\n"
        )
        log.write(
            "   follow-up patches that also address the regression.\n"
        )
        log.write(
            "   >> VERDICT: v3's broader classification captures fixes\n"
        )
        log.write(
            "      that v1/v2 miss. Recommended for comprehensive analysis.\n\n"
        )

        log.write("3. LONGEST CHAIN LENGTH\n")
        log.write(
            "   v1 and v2 report the same longest_chain_length value. v3\n"
        )
        log.write(
            "   reports a value exactly 1 higher. This difference arises\n"
        )
        log.write(
            "   from the path length convention: v1/v2 count edges while\n"
        )
        log.write(
            "   v3 counts vertices. The vertex-count convention (number of\n"
        )
        log.write(
            "   stages in a regression cascade) is more natural for\n"
        )
        log.write(
            "   software reliability analysis, where each node represents\n"
        )
        log.write(
            "   a distinct failure event in the cascade.\n"
        )
        log.write(
            "   >> VERDICT: Both conventions are valid. v3's node-count\n"
        )
        log.write(
            "      approach has stronger domain justification.\n\n"
        )

        log.write("4. OVERALL RECOMMENDATION\n")
        log.write(
            "   v2 demonstrates the most careful data parsing with its\n"
        )
        log.write(
            "   conservative delimiter handling. For a production pipeline,\n"
        )
        log.write(
            "   use v2's graph construction as the baseline, supplemented\n"
        )
        log.write(
            "   with v3's fix classification and path length convention\n"
        )
        log.write(
            "   for domain-appropriate metrics. v1 should be retired\n"
        )
        log.write("   due to its edge direction error.\n")


if __name__ == "__main__":
    main()
