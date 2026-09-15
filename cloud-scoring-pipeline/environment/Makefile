PYTHON = python
DETECTOR_DIR = baseline
PREDICTIONS_DIR = predictions
RESULTS_DIR = results
DATA_DIR = data

.PHONY: detect validate score clean

detect:
	$(PYTHON) $(DETECTOR_DIR)/main.py

validate:
	$(PYTHON) -m pytest tests/test_submission.py -v

score: validate
	$(PYTHON) scoring/metric.py $(PREDICTIONS_DIR) $(DATA_DIR)/test_labels $(RESULTS_DIR)/score.json

clean:
	rm -rf $(PREDICTIONS_DIR) $(RESULTS_DIR)
