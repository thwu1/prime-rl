#!/usr/bin/env python3
"""Generate OWASP Benchmark-style evaluation data for the scoring engine task.

Creates expected results, tool scan results, and configuration only.
No reference scorecard or pipeline code is generated — the solver must build those.
"""
import json
import os


def main():
    os.makedirs("/app/data/tool_results", exist_ok=True)
    os.makedirs("/app/output", exist_ok=True)
    os.makedirs("/app/reference", exist_ok=True)

    # Category definitions: (name, cwe, true_start, true_end, false_start, false_end)
    # Intentionally imbalanced sizes to require correct averaging methodology
    categories = [
        ("cmdi",       78,   1,  12,  13,  20),   # 12 true, 8 false = 20
        ("sqli",       89,  21,  35,  36,  45),   # 15 true, 10 false = 25
        ("xss",        79,  46,  55,  56,  65),   # 10 true, 10 false = 20
        ("crypto",    327,  66,  73,  74,  80),   #  8 true,  7 false = 15
        ("hash",      328,  81,  92,  93, 100),   # 12 true,  8 false = 20
        ("pathtraver", 22, 101, 110, 111, 120),   # 10 true, 10 false = 20
    ]

    # --- Generate expected results CSV ---
    with open("/app/data/expected_results.csv", "w") as f:
        f.write("# test name, category, real vulnerability, cwe, "
                "Benchmark version: 1.2, 2016-06-1\n")
        for cat_name, cwe, ts, te, fs, fe in categories:
            for i in range(ts, te + 1):
                f.write(f"BenchmarkTest{i:05d},{cat_name},true,{cwe}\n")
            for i in range(fs, fe + 1):
                f.write(f"BenchmarkTest{i:05d},{cat_name},false,{cwe}\n")

    # --- Generate config.yaml ---
    config_content = (
        'benchmark_version: "1.2"\n'
        'expected_results_file: "expected_results.csv"\n'
        'tools:\n'
        '  - name: "ToolAlpha"\n'
        '    results_file: "tool_results/tool_alpha.jsonl"\n'
        '    commercial: false\n'
        '  - name: "AppScanLike"\n'
        '    results_file: "tool_results/tool_appscan.jsonl"\n'
        '    commercial: true\n'
        '  - name: "ToolGamma"\n'
        '    results_file: "tool_results/tool_gamma.jsonl"\n'
        '    commercial: false\n'
        '  - name: "ToolDelta"\n'
        '    results_file: "tool_results/tool_delta.jsonl"\n'
        '    commercial: true\n'
        'cwe_exceptions:\n'
        '  - expected_cwe: 564\n'
        '    accepted_cwe: 89\n'
        '    tool_prefixes: ["*"]\n'
        '  - expected_cwe: 328\n'
        '    accepted_cwe: 327\n'
        '    tool_prefixes: ["AppScan", "Vera", "CodeQL"]\n'
    )
    with open("/app/data/config.yaml", "w") as f:
        f.write(config_content)

    # --- Helper ---
    def write_findings(filepath, findings):
        with open(filepath, "w") as f:
            for test_id, cwe in findings:
                line = json.dumps({"test_name": f"BenchmarkTest{test_id:05d}",
                                   "cwe": cwe})
                f.write(line + "\n")

    # --- ToolAlpha: Good baseline tool ---
    alpha = []
    alpha.extend([(i, 78)  for i in range(1, 11)])    # cmdi TP: 001-010 (10/12)
    alpha.extend([(i, 78)  for i in range(13, 15)])    # cmdi FP: 013-014 (2/8)
    alpha.extend([(i, 89)  for i in range(21, 33)])    # sqli TP: 021-032 (12/15)
    alpha.append((36, 89))                              # sqli FP: 036     (1/10)
    alpha.extend([(i, 79)  for i in range(46, 54)])    # xss TP:  046-053 (8/10)
    alpha.extend([(i, 79)  for i in range(56, 58)])    # xss FP:  056-057 (2/10)
    alpha.extend([(i, 327) for i in range(66, 72)])    # crypto TP: 066-071 (6/8)
    alpha.append((74, 327))                             # crypto FP: 074    (1/7)
    alpha.extend([(i, 328) for i in range(81, 89)])    # hash TP: 081-088  (8/12)
    alpha.extend([(i, 328) for i in range(93, 95)])    # hash FP: 093-094  (2/8)
    alpha.extend([(i, 22)  for i in range(101, 109)])  # pathtraver TP: 101-108 (8/10)
    alpha.append((111, 22))                             # pathtraver FP: 111    (1/10)
    write_findings("/app/data/tool_results/tool_alpha.jsonl", alpha)

    # --- AppScanLike: Reports CWE 327 for hash tests (CWE 328) ---
    appscan = []
    appscan.extend([(i, 78)  for i in range(1, 8)])     # cmdi TP: 001-007 (7/12)
    appscan.extend([(i, 78)  for i in range(13, 16)])   # cmdi FP: 013-015 (3/8)
    appscan.extend([(i, 89)  for i in range(21, 31)])   # sqli TP: 021-030 (10/15)
    appscan.extend([(i, 89)  for i in range(36, 38)])   # sqli FP: 036-037 (2/10)
    appscan.extend([(i, 79)  for i in range(46, 53)])   # xss TP:  046-052 (7/10)
    appscan.extend([(i, 79)  for i in range(56, 59)])   # xss FP:  056-058 (3/10)
    appscan.extend([(i, 327) for i in range(66, 71)])   # crypto TP: 066-070 (5/8)
    appscan.extend([(i, 327) for i in range(74, 76)])   # crypto FP: 074-075 (2/7)
    appscan.extend([(i, 327) for i in range(81, 89)])   # hash TP: 081-088 CWE=327 (8/12)
    appscan.extend([(i, 327) for i in range(93, 96)])   # hash FP: 093-095 CWE=327 (3/8)
    appscan.extend([(i, 22)  for i in range(101, 108)]) # pathtraver TP: 101-107 (7/10)
    appscan.extend([(i, 22)  for i in range(111, 113)]) # pathtraver FP: 111-112 (2/10)
    write_findings("/app/data/tool_results/tool_appscan.jsonl", appscan)

    # --- ToolGamma: Aggressive tool with duplicate findings ---
    gamma = []
    gamma.extend([(i, 78) for i in range(1, 13)])      # cmdi TP: 001-012 (12/12)
    gamma.append((1, 79))                                # EXTRA: test 001, wrong CWE
    gamma.extend([(i, 78) for i in range(13, 15)])      # cmdi FP: 013-014 (2/8)
    gamma.extend([(i, 89) for i in range(21, 36)])      # sqli TP: 021-035 (15/15)
    gamma.extend([(i, 89) for i in range(36, 38)])      # sqli FP: 036-037 (2/10)
    gamma.extend([(i, 79) for i in range(46, 56)])      # xss TP:  046-055 (10/10)
    gamma.extend([(i, 79) for i in range(56, 60)])      # xss FP:  056-059 (4/10)
    gamma.extend([(i, 327) for i in range(66, 69)])     # crypto TP: 066-068 (3/8)
    gamma.extend([(i, 327) for i in range(74, 80)])     # crypto FP: 074-079 (6/7)
    gamma.append((74, 328))                              # EXTRA: test 074, different CWE
    gamma.extend([(i, 328) for i in range(81, 90)])     # hash TP: 081-089 (9/12)
    gamma.extend([(i, 328) for i in range(93, 98)])     # hash FP: 093-097 (5/8)
    gamma.extend([(i, 22) for i in range(101, 111)])    # pathtraver TP: 101-110 (10/10)
    gamma.extend([(i, 22) for i in range(111, 117)])    # pathtraver FP: 111-116 (6/10)
    write_findings("/app/data/tool_results/tool_gamma.jsonl", gamma)

    # --- ToolDelta: Conservative tool ---
    delta = []
    delta.extend([(i, 78)  for i in range(1, 5)])      # cmdi TP: 001-004 (4/12)
    delta.extend([(i, 89)  for i in range(21, 27)])     # sqli TP: 021-026 (6/15)
    delta.append((36, 89))                               # sqli FP: 036     (1/10)
    delta.extend([(i, 79)  for i in range(46, 50)])     # xss TP:  046-049 (4/10)
    delta.extend([(i, 327) for i in range(66, 69)])     # crypto TP: 066-068 (3/8)
    delta.append((74, 327))                              # crypto FP: 074    (1/7)
    delta.extend([(i, 328) for i in range(81, 86)])     # hash TP: 081-085 (5/12)
    delta.extend([(i, 22)  for i in range(101, 106)])   # pathtraver TP: 101-105 (5/10)
    delta.append((111, 22))                              # pathtraver FP: 111    (1/10)
    write_findings("/app/data/tool_results/tool_delta.jsonl", delta)

    print("Data generated: 6 categories, 120 test cases, 4 tools")


if __name__ == "__main__":
    main()
