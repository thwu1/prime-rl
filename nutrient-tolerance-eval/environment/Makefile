.PHONY: evaluate clean

DB = /app/pipeline.db

evaluate: /app/output/results.json

$(DB): /app/data/ground_truth.json /app/data/tolerance_rules.json /app/data/fsa_thresholds.json /app/config/pipeline_config.toml /app/src/load_data.py
	python3 /app/src/load_data.py

/app/.tolerance_done: $(DB) /app/src/tolerance_check.py
	python3 /app/src/tolerance_check.py && touch $@

/app/.fsa_done: $(DB) /app/src/fsa_labeler.py
	python3 /app/src/fsa_labeler.py && touch $@

/app/.error_analysis_done: $(DB) /app/src/error_analysis.py
	python3 /app/src/error_analysis.py && touch $@

/app/.scoring_done: /app/.tolerance_done /app/.fsa_done /app/src/scoring.py
	python3 /app/src/scoring.py && touch $@

/app/.significance_done: /app/.scoring_done /app/src/significance.py
	python3 /app/src/significance.py && touch $@

/app/output/results.json: /app/.significance_done /app/src/report.py
	python3 /app/src/report.py

clean:
	rm -f $(DB) /app/output/results.json /app/.tolerance_done /app/.fsa_done /app/.error_analysis_done /app/.scoring_done /app/.significance_done
