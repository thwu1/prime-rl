.PHONY: all data calibrate validate report clean

all: validate report

data:
	python3 /app/generate_data.py

calibrate:
	python3 /app/pipeline.py

validate: calibrate
	bash /app/validate.sh /app/results.json

report: validate
	python3 /app/report.py

clean:
	rm -f /app/data/predictions.npz /app/calibration.db /app/results.json /app/report.txt
