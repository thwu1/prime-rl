#!/usr/bin/env python3
"""Fix the jq report template and generate summary_report.json.

The report_template.jq has two bugs:
1. .ranking[0].j should be .ranking[0].youdens_j (wrong field name)
2. .value.tpr == "0" compares against string instead of number (should be == 0)
"""
import subprocess


def main():
    with open("/app/report_template.jq") as f:
        content = f.read()

    # Fix bug 1: wrong field name for youdens_j
    content = content.replace(".ranking[0].j", ".ranking[0].youdens_j")

    # Fix bug 2: string-to-number type mismatch in tpr comparison
    content = content.replace('.value.tpr == "0"', ".value.tpr == 0")

    with open("/app/report_template.jq", "w") as f:
        f.write(content)

    # Generate summary report using fixed jq template
    with open("/app/output/summary_report.json", "w") as out:
        subprocess.run(
            ["jq", "-f", "/app/report_template.jq", "/app/output/scorecard.json"],
            stdout=out,
            check=True,
        )

    print("Summary report generated at /app/output/summary_report.json")


if __name__ == "__main__":
    main()
