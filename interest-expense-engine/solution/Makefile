.PHONY: all clean report

all: results.db

results.db: data/entities.csv data/financials.csv data/partnerships.csv data/ownership.csv data/intercompany_loans.csv data/distributions.csv compute163j.py
	python3 compute163j.py

report: results.db
	bash gen_report.sh

clean:
	rm -f results.db report.json
