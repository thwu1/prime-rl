An SGLang LLM inference server's Prometheus metrics have been collected across three scrape snapshots. The raw scrape data is at `/app/scrapes/`, scrape timestamps are in `/app/scrape_metadata.json`, and SLO definitions with alert thresholds are in `/app/slo_config.json`.

Produce three artifacts:

### `/app/report.json`

```json
{
  "counter_rates": {
    "<metric_name>": {
      "interval_0_1": <per_second_rate>,
      "interval_1_2": <per_second_rate>
    }
  },
  "interval_percentiles": {
    "<histogram_metric>": {
      "interval_0_1": {"p50": <float>, "p95": <float>, "p99": <float>},
      "interval_1_2": {"p50": <float>, "p95": <float>, "p99": <float>}
    }
  },
  "slo_evaluation": {
    "<slo_name>": {
      "interval_results": [<bool>, <bool>],
      "compliance_ratio": <float>,
      "burn_rate": <float>,
      "alert_level": "<critical|warning|none>"
    }
  }
}
```

All rates and percentile estimations must be computed per-interval (between consecutive scrapes) and must be consistent with standard Prometheus semantics for the respective metric types. SLO evaluation derives from the definitions and alert thresholds in the config file.

### `/app/recording_rules.yml`

Valid Prometheus recording rules expressing the derived metric computations (rates for counters, percentiles for histograms) as PromQL. Must pass `promtool check rules /app/recording_rules.yml`.

### `/app/alerting_rules.yml`

Valid Prometheus alerting rules implementing SLO-based alerting per `/app/slo_config.json`, with severity levels corresponding to the configured burn-rate thresholds. Must pass `promtool check rules /app/alerting_rules.yml`.

`promtool` is installed at `/usr/local/bin/promtool`.