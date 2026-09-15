# LandCoverNet Pipeline Orchestration
DATA_DIR = /app/data
RESULTS_DB = /app/results.db

.PHONY: help init-db assess-sample score-sample report pipeline clean

help:
	@echo "Targets: init-db, assess-sample, score-sample, report, pipeline, clean"

init-db:
	cd /app && python3 -c "from lcnet.storage import init_db; init_db('$(RESULTS_DB)')"

assess-sample: init-db
	cd /app && python3 -m lcnet assess $(DATA_DIR)/predictions_sample.csv $(DATA_DIR)/truth_sample.csv --level 3 --db $(RESULTS_DB)

score-sample: init-db
	cd /app && python3 -m lcnet score $(DATA_DIR)/submission_sample.csv $(DATA_DIR)/sub_truth_sample.csv --db $(RESULTS_DB)

report:
	@sqlite3 $(RESULTS_DB) "SELECT level, COUNT(*), AVG(overall_accuracy), AVG(cohens_kappa) FROM assessments GROUP BY level"

pipeline: init-db assess-sample score-sample report

clean:
	rm -f $(RESULTS_DB)
