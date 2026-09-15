DB = /app/benchmark.db
PIPELINES = /app/pipelines
OUTPUTS = /app/outputs

.PHONY: run-all run-alpha run-beta run-gamma compare compare-beta reconcile schema validate show-draft explore export-ndjson final clean

run-all: run-alpha run-beta run-gamma

run-alpha:
	python3 $(PIPELINES)/alpha.py

run-beta:
	python3 $(PIPELINES)/beta.py

run-gamma:
	python3 $(PIPELINES)/gamma.py

schema:
	@sqlite3 $(DB) ".schema"
	@echo "--- Views ---"
	@sqlite3 $(DB) "SELECT sql FROM sqlite_master WHERE type='view';"

compare:
	@echo "=== scaled_pass1 (JSON prototypes) ==="
	@for f in $(OUTPUTS)/*.json; do printf "%-10s " "$$(basename $$f .json):"; jq -c '.scaled_pass1' "$$f"; done
	@echo ""
	@echo "=== contamination_safe_scaled_pass1 (JSON prototypes) ==="
	@for f in $(OUTPUTS)/*.json; do printf "%-10s " "$$(basename $$f .json):"; jq -c '.contamination_safe_scaled_pass1' "$$f"; done
	@echo ""
	@echo "=== paper_ablation_impact (JSON prototypes) ==="
	@for f in $(OUTPUTS)/*.json; do printf "%-10s " "$$(basename $$f .json):"; jq -c '.paper_ablation_impact' "$$f"; done
	@echo ""
	@echo "=== bootstrap_ci aurora-72b (JSON prototypes) ==="
	@for f in $(OUTPUTS)/*.json; do printf "%-10s " "$$(basename $$f .json):"; jq -c '.bootstrap_ci["aurora-72b"]' "$$f"; done
	@echo ""
	@echo "=== ranking (JSON prototypes) ==="
	@for f in $(OUTPUTS)/*.json; do printf "%-10s " "$$(basename $$f .json):"; jq -c '[.ranking[] | .model_id]' "$$f"; done

compare-beta:
	@echo "=== Beta (CSV) scaled_pass1 ==="
	@mlr --csv --opprint cat $(OUTPUTS)/beta/scaled_pass1.csv
	@echo ""
	@echo "=== Beta (CSV) contamination_safe ==="
	@mlr --csv --opprint cat $(OUTPUTS)/beta/contamination_safe.csv
	@echo ""
	@echo "=== Beta (CSV) paper_ablation ==="
	@mlr --csv --opprint cat $(OUTPUTS)/beta/paper_ablation.csv
	@echo ""
	@echo "=== Beta (CSV) bootstrap_ci ==="
	@mlr --csv --opprint cat $(OUTPUTS)/beta/bootstrap_ci.csv
	@echo ""
	@echo "=== Beta (CSV) ranking ==="
	@mlr --csv --opprint cat $(OUTPUTS)/beta/ranking.csv

reconcile:
	@echo "=== Cross-format reconciliation: scaled_pass1 ==="
	@echo "Alpha (JSON, LOC-weighted):"
	@jq -r '.scaled_pass1 | to_entries[] | "  \(.key): \(.value)"' $(OUTPUTS)/alpha.json
	@echo "Beta (CSV, count-based):"
	@csvjson $(OUTPUTS)/beta/scaled_pass1.csv | jq -r '.[] | "  \(.model_id): \(.score)"'
	@echo "Gamma (JSON, LOC-weighted):"
	@jq -r '.scaled_pass1 | to_entries[] | "  \(.key): \(.value)"' $(OUTPUTS)/gamma.json
	@echo ""
	@echo "=== Cross-format reconciliation: contamination_safe ==="
	@echo "Alpha (JSON, >= boundary):"
	@jq -r '.contamination_safe_scaled_pass1 | to_entries[] | "  \(.key): \(.value)"' $(OUTPUTS)/alpha.json
	@echo "Beta (CSV, > boundary, null-aware):"
	@csvjson $(OUTPUTS)/beta/contamination_safe.csv | jq -r '.[] | "  \(.model_id): \(.score // "null")"'
	@echo "Gamma (JSON, > boundary, no null):"
	@jq -r '.contamination_safe_scaled_pass1 | to_entries[] | "  \(.key): \(.value)"' $(OUTPUTS)/gamma.json
	@echo ""
	@echo "=== Contamination boundary cases from DB view ==="
	@sqlite3 $(DB) "SELECT model_id, paper_id, safety_status FROM v_model_paper_contamination WHERE repo_first_commit = knowledge_cutoff ORDER BY model_id, paper_id;"
	@echo ""
	@echo "=== Cross-format reconciliation: paper_ablation ==="
	@echo "Alpha (JSON, reversed direction):"
	@jq -r '.paper_ablation_impact | to_entries[] | "  \(.key): \(.value)"' $(OUTPUTS)/alpha.json
	@echo "Beta (CSV, correct direction):"
	@csvjson $(OUTPUTS)/beta/paper_ablation.csv | jq -r '.[] | "  \(.model_id): \(.impact)"'
	@echo "Gamma (JSON, correct direction):"
	@jq -r '.paper_ablation_impact | to_entries[] | "  \(.key): \(.value)"' $(OUTPUTS)/gamma.json
	@echo ""
	@echo "=== Bootstrap parameter differences ==="
	@echo "Alpha: seed=2024, iters=10000, snippet-level"
	@echo "Beta (CSV): seed=42, iters=1000, snippet-level"
	@echo "Gamma: seed=2024, iters=10000, paper-level"

explore:
	@echo "=== Paper complexity (NDJSON via jq) ==="
	@jq -s 'sort_by(.total_loc) | reverse | .[] | "\(.paper_id): \(.num_snippets) snippets, \(.total_loc) LOC"' /app/data/ndjson/paper_complexity.ndjson
	@echo ""
	@echo "=== Model cutoffs (CSV via mlr) ==="
	@mlr --csv --opprint cat /app/data/csv/models.csv
	@echo ""
	@echo "=== Contamination summary per model (NDJSON via jq) ==="
	@jq -s 'group_by(.model_id) | .[] | {model: .[0].model_id, safe: [.[] | select(.safety_status=="safe")] | length, contaminated: [.[] | select(.safety_status=="contaminated")] | length}' /app/data/ndjson/contamination.ndjson
	@echo ""
	@echo "=== LOC distribution by paper (CSV via csvsql) ==="
	@csvsql --query "SELECT paper_id, COUNT(*) as n_snippets, SUM(lines_of_code) as total_loc, ROUND(CAST(AVG(lines_of_code) AS FLOAT),1) as avg_loc FROM snippets GROUP BY paper_id ORDER BY total_loc DESC" /app/data/csv/snippets.csv
	@echo ""
	@echo "=== Results summary (CSV via mlr) ==="
	@mlr --csv stats1 -a count,sum -f with_paper,without_paper /app/data/csv/results.csv

show-draft:
	@echo "=== Draft Analysis Keys ==="
	@jq -c 'keys' /app/output/draft_analysis.json 2>/dev/null || echo "No draft output"
	@echo ""
	@echo "=== Pairwise Significance (significant pairs) ==="
	@jq -r '.pairwise_significance // {} | to_entries[] | select(.value.significant) | .key' /app/output/draft_analysis.json 2>/dev/null || true
	@echo ""
	@echo "=== Jackknife SEs ==="
	@jq -r '.jackknife_stability // {} | to_entries[] | "\(.key): SE=\(.value.jackknife_se), influential=\(.value.most_influential_paper)"' /app/output/draft_analysis.json 2>/dev/null || true

validate:
	@test -f /app/output/analysis.json || (echo "ERROR: /app/output/analysis.json not found" && exit 1)
	@echo "=== Output structure ==="
	@echo "Keys: $$(jq -c 'keys' /app/output/analysis.json)"
	@echo "Models in scaled_pass1: $$(jq '.scaled_pass1 | length' /app/output/analysis.json)"
	@echo "Ranking length: $$(jq '.ranking | length' /app/output/analysis.json)"
	@echo "Pairwise pairs: $$(jq '.pairwise_significance | length' /app/output/analysis.json)"
	@echo "Jackknife models: $$(jq '.jackknife_stability | length' /app/output/analysis.json)"
	@jq -e '.contamination_safe_scaled_pass1 | to_entries[] | select(.value == null) | .key' /app/output/analysis.json > /dev/null 2>&1 && echo "Null scores present: yes" || echo "Null scores present: no"
	@echo ""
	@echo "=== Cross-validate scaled_pass1 against CSV data ==="
	@jq -r '.scaled_pass1 | to_entries | sort_by(.key) | .[] | [.key, .value] | @csv' /app/output/analysis.json > /tmp/analysis_sp1.csv
	@echo "model_id,score" | cat - /tmp/analysis_sp1.csv > /tmp/analysis_sp1_h.csv
	@mlr --csv join -j model_id -f /app/data/csv/models.csv /tmp/analysis_sp1_h.csv
	@rm -f /tmp/analysis_sp1.csv /tmp/analysis_sp1_h.csv
	@echo ""
	@echo "=== Ranking verification via jq ==="
	@jq -r '.ranking[] | "\(.rank // "null")\t\(.model_id)\t\(.contamination_safe_score // "null")"' /app/output/analysis.json

export-ndjson:
	@echo "Exporting analysis to NDJSON for external validation..."
	@jq -r '.scaled_pass1 | to_entries[] | {metric: "scaled_pass1", model_id: .key, value: .value}' /app/output/analysis.json | jq -c '.'
	@jq -r '.contamination_safe_scaled_pass1 | to_entries[] | {metric: "contamination_safe", model_id: .key, value: .value}' /app/output/analysis.json | jq -c '.'

final:
	python3 /app/pipeline.py

clean:
	rm -rf $(OUTPUTS) /app/output
