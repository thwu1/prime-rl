#!/bin/bash


pip3 install numpy==2.1.3 -q

# Fix bugs and implement alignment
python3 /solution/fix_all.py

# Run evaluation (generates DB, PLY files, and JSON report)
python3 /solution/evaluate.py

# Use jq to extract outlier IDs from the noisy scene
jq '[.noisy.point_data[] | select(.is_inlier == 0) | .point_id]' /app/output/report.json > /app/output/outlier_ids.json

# Use jq to extract metrics summary
jq '{clean_rmse: .clean.rmse, noisy_rmse: .noisy.rmse, noisy_inlier_ratio: .noisy.inlier_ratio}' /app/output/report.json > /app/output/metrics_summary.json

# Use sqlite3 CLI to create outlier analysis view with correlated subquery
sqlite3 /app/results.db "CREATE VIEW IF NOT EXISTS outlier_analysis AS SELECT qm.scene_name, qm.num_points, qm.num_inliers, (qm.num_points - qm.num_inliers) AS num_outliers, qm.rmse, COALESCE((SELECT AVG(pc.residual) FROM point_classifications pc WHERE pc.scene_name = qm.scene_name AND pc.is_inlier = 0), 0.0) AS mean_outlier_residual FROM quality_metrics qm;"

# Export view as CSV with headers using sqlite3 CLI
sqlite3 -header -csv /app/results.db "SELECT * FROM outlier_analysis ORDER BY scene_name;" > /app/output/outlier_report.csv
