.PHONY: all analyze visualize report

all:
	$(MAKE) analyze
	$(MAKE) visualize
	$(MAKE) report

analyze:
	python3 /app/optimizer.py

visualize:
	@for f in /app/results/*.cfg.json; do \
		name=$$(basename $$f .cfg.json); \
		python3 /app/cfg_to_dot.py $$f | dot -Tsvg -o /app/results/$$name.cfg.svg; \
	done

report:
	@jq -n \
		--slurpfile p1 /app/results/prog1.constprop.json \
		--slurpfile p2 /app/results/prog2.constprop.json \
		--slurpfile p3 /app/results/prog3.constprop.json \
		'{prog1: $$p1[0], prog2: $$p2[0], prog3: $$p3[0]}' \
		> /app/results/summary.json
