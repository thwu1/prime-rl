# Parallel Program Analyzer Pipeline

PROGS = $(wildcard programs/*.json)

analyze:
	python3 analyzer.py $(PROGS)

graphs:
	for f in graphs/*.dot; do dot -Tpng $$f > $${f%.dot}.svg; done

validate:
	for f in results/*.json; do jq '.name, .work, .span' $$f; done

all: graphs validate analyze

clean:
	rm -rf results/ graphs/
