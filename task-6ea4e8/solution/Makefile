
PROGRAMS = propagation loop_analysis diamond_flow tricky

.PHONY: all optimize cfg verify report clean

all: optimize cfg verify report

optimize:
	@mkdir -p /app/optimized
	@for p in $(PROGRAMS); do \
		python3 /app/optimizer.py /app/programs/$$p.tac > /app/optimized/$$p.tac; \
		echo "Optimized $$p.tac"; \
	done

cfg: optimize
	@mkdir -p /app/cfg
	@for p in $(PROGRAMS); do \
		python3 /app/cfg_gen.py /app/programs/$$p.tac "$$p (before)" > /app/cfg/$${p}_before.dot; \
		dot -Tsvg /app/cfg/$${p}_before.dot -o /app/cfg/$${p}_before.svg; \
		python3 /app/cfg_gen.py /app/optimized/$$p.tac "$$p (after)" > /app/cfg/$${p}_after.dot; \
		dot -Tsvg /app/cfg/$${p}_after.dot -o /app/cfg/$${p}_after.svg; \
		echo "Generated CFG for $$p"; \
	done

verify: optimize
	@for p in $(PROGRAMS); do \
		orig=$$(python3 /app/tac_interpreter.py /app/programs/$$p.tac); \
		opt=$$(python3 /app/tac_interpreter.py /app/optimized/$$p.tac); \
		if [ "$$orig" = "$$opt" ]; then \
			echo "$$p: PASS"; \
		else \
			echo "$$p: FAIL (output mismatch)"; \
			exit 1; \
		fi; \
	done

report: optimize
	@python3 /app/report_gen.py > /app/report.json
	@echo "Report written to /app/report.json"

clean:
	rm -rf /app/optimized /app/cfg /app/report.json
