#!/bin/bash
# Post-processing: extract marginal distributions, generate hazard curve plot,
# and create comprehensive analysis report from pipeline outputs.
#
# Tools used: sqlite3 (marginal queries), gnuplot (plotting), jq (JSON merge)

OUTPUT_DIR="/app/output"
PIPELINE_DIR="/app/pipeline"

# Step 1: Extract marginal magnitude distribution from disaggregation database
sqlite3 -header -csv "$OUTPUT_DIR/disagg.db" \
  "SELECT mag_center, AVG(contribution) as marginal FROM bins GROUP BY mag_center ORDER BY mag_center;" \
  > "$OUTPUT_DIR/marginal_mag.csv"

# Step 2: Extract marginal distance distribution
sqlite3 -header -csv "$OUTPUT_DIR/disagg.db" \
  "SELECT dist_center, AVG(contribution) as marginal FROM bins GROUP BY dist_center ORDER BY dist_center;" \
  > "$OUTPUT_DIR/marginal_dist.csv"

# Step 3: Generate hazard curve plot
gnuplot "$PIPELINE_DIR/hazard_plot.gp"

# Step 4: Create comprehensive report by merging configuration and results
jq -n \
  --argjson site "$(cat /app/model/site.json)" \
  --argjson config "$(cat /app/model/config.json)" \
  --argjson disagg "$(cat $OUTPUT_DIR/disagg_summary.json)" \
  '{
    report_type: "seismic_hazard_analysis",
    site: {
      name: $site.name,
      longitude: $site.lon,
      latitude: $site.lat,
      vs30_m_s: $site.vs30
    },
    analysis: {
      imt: $config.imt,
      return_period_years: $config.disaggregation.return_period,
      exposure_years: $config.exposure,
      num_imls: ($config.imls | length)
    },
    disaggregation: {
      target_iml_g: $disagg.target_iml,
      modal_magnitude: $disagg.modal_mag,
      modal_distance_km: $disagg.modal_dist,
      mean_epsilon: $disagg.mean_epsilon,
      annual_exceedance_rate: $disagg.total_rate_at_target
    }
  }' > "$OUTPUT_DIR/disagg_report.json"

echo "Post-processing complete"
