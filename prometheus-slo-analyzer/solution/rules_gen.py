#!/usr/bin/env python3
"""Generate Prometheus recording and alerting rules from SGLang metrics and SLO config."""


import json


RECORDING_RULES = """groups:
  - name: sglang_counter_rates
    rules:
      - record: sglang:prompt_tokens_rate
        expr: rate(sglang:prompt_tokens_total[10m])
      - record: sglang:generation_tokens_rate
        expr: rate(sglang:generation_tokens_total[10m])
  - name: sglang_histogram_percentiles
    rules:
      - record: sglang:ttft_p50
        expr: histogram_quantile(0.50, rate(sglang:time_to_first_token_seconds_bucket[10m]))
      - record: sglang:ttft_p95
        expr: histogram_quantile(0.95, rate(sglang:time_to_first_token_seconds_bucket[10m]))
      - record: sglang:ttft_p99
        expr: histogram_quantile(0.99, rate(sglang:time_to_first_token_seconds_bucket[10m]))
      - record: sglang:e2e_p50
        expr: histogram_quantile(0.50, rate(sglang:e2e_request_latency_seconds_bucket[10m]))
      - record: sglang:e2e_p95
        expr: histogram_quantile(0.95, rate(sglang:e2e_request_latency_seconds_bucket[10m]))
      - record: sglang:e2e_p99
        expr: histogram_quantile(0.99, rate(sglang:e2e_request_latency_seconds_bucket[10m]))
"""


def generate_alert_rule(name, expr, duration, severity, slo, summary):
    """Generate a single YAML alert rule block."""
    return (
        f"      - alert: {name}\n"
        f"        expr: {expr}\n"
        f"        for: {duration}\n"
        f"        labels:\n"
        f"          severity: {severity}\n"
        f"          slo: {slo}\n"
        f"        annotations:\n"
        f'          summary: "{summary}"\n'
    )


def main():
    with open("/app/slo_config.json") as f:
        slo_config = json.load(f)

    # Write recording rules
    with open("/app/recording_rules.yml", "w") as f:
        f.write(RECORDING_RULES)

    # Generate alerting rules from SLO config
    alert_config = slo_config["alert_rules"]
    critical_br = alert_config["critical"]["burn_rate_threshold"]
    warning_br = alert_config["warning"]["burn_rate_threshold"]

    rule_blocks = []
    for slo in slo_config["slos"]:
        metric = slo["metric"]
        pct = slo["percentile"]
        threshold = slo["threshold"]
        slo_name = slo["name"]

        pct_expr_short = (
            f"histogram_quantile({pct}, rate({metric}_bucket[1h])) > {threshold}"
        )
        pct_expr_long = (
            f"histogram_quantile({pct}, rate({metric}_bucket[6h])) > {threshold}"
        )

        rule_blocks.append(generate_alert_rule(
            name=f"{slo_name}_critical",
            expr=pct_expr_short,
            duration="2m",
            severity="critical",
            slo=slo_name,
            summary=f"{slo_name} SLO breached, burn rate exceeds {critical_br}",
        ))
        rule_blocks.append(generate_alert_rule(
            name=f"{slo_name}_warning",
            expr=pct_expr_long,
            duration="15m",
            severity="warning",
            slo=slo_name,
            summary=f"{slo_name} SLO at risk, burn rate exceeds {warning_br}",
        ))

    with open("/app/alerting_rules.yml", "w") as f:
        f.write("groups:\n")
        f.write("  - name: sglang_slo_alerts\n")
        f.write("    rules:\n")
        for block in rule_blocks:
            f.write(block)


if __name__ == "__main__":
    main()
