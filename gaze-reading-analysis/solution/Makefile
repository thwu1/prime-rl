.PHONY: all clean

DATA_DIR := /app/data
OUTPUT_DIR := /app/output

all: $(OUTPUT_DIR)/gaze.db

$(OUTPUT_DIR)/.pipeline_done: /app/analyze.py
	python3 /app/analyze.py --data-dir $(DATA_DIR) --output-dir $(OUTPUT_DIR)
	touch $@

$(OUTPUT_DIR)/gaze.db: $(OUTPUT_DIR)/.pipeline_done
	rm -f $@
	sqlite3 -cmd ".mode csv" $@ ".import $(OUTPUT_DIR)/fixations.csv fixations"
	sqlite3 -cmd ".mode csv" $@ ".import $(OUTPUT_DIR)/saccades.csv saccades"
	sqlite3 -cmd ".mode csv" $@ ".import $(OUTPUT_DIR)/reading_measures.csv reading_measures"
	sqlite3 $@ "CREATE VIEW reader_summary AS SELECT SUBSTR(trial_id, 1, INSTR(trial_id, '_') - 1) AS reader_id, AVG(CASE WHEN was_skipped + 0 = 0 THEN first_fixation_duration * 1.0 END) AS mean_ffd, AVG(CASE WHEN was_skipped + 0 = 0 THEN gaze_duration * 1.0 END) AS mean_gd, SUM(CASE WHEN was_skipped + 0 = 1 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS skip_rate, SUM(CASE WHEN was_regressed_to + 0 = 1 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS regression_rate FROM reading_measures GROUP BY reader_id;"
	sqlite3 $@ "CREATE VIEW passage_difficulty AS SELECT SUBSTR(trial_id, INSTR(trial_id, '_') + 1) AS passage_id, AVG(total_reading_time * 1.0) AS mean_trt, SUM(CASE WHEN was_skipped + 0 = 1 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS mean_skip_rate FROM reading_measures GROUP BY passage_id;"
	sqlite3 $@ "CREATE VIEW processing_difficulty AS SELECT SUBSTR(trial_id, INSTR(trial_id, '_') + 1) AS passage_id, word_idx, AVG(CASE WHEN was_skipped + 0 = 0 THEN go_past_time * 1.0 END) AS mean_gpt, AVG(CASE WHEN was_skipped + 0 = 0 THEN (go_past_time - gaze_duration) * 1.0 END) AS regression_cost, AVG(CASE WHEN first_fixation_landing + 0.0 >= 0 THEN first_fixation_landing + 0.0 END) AS mean_landing FROM reading_measures GROUP BY SUBSTR(trial_id, INSTR(trial_id, '_') + 1), word_idx;"

clean:
	rm -rf $(OUTPUT_DIR)
