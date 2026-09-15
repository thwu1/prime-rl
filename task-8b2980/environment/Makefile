.PHONY: all validate profile-all constraints costs requirements clean

all: validate

validate: /app/strategies.py
	@echo "=== Validating all strategies ==="
	@./dtrain run fsdp
	@./dtrain run gpipe
	@./dtrain run pipeline_fsdp
	@echo "=== All strategies passed ==="

profile-%: /app/strategies.py
	@./dtrain profile $* | jq '{strategy: .strategy, config: .config, ranks: [.per_rank[] | {rank: .rank, time: .total_time, peak_memory: .peak_memory, events: .event_count}]}'

profile-all: /app/strategies.py
	@for s in fsdp gpipe pipeline_fsdp; do \
		echo "=== $$s ==="; \
		./dtrain profile $$s | jq '{strategy: .strategy, config: .config, ranks: [.per_rank[] | {rank: .rank, time: .total_time, peak_memory: .peak_memory}]}'; \
	done

constraints:
	@sqlite3 /app/constraints.db "SELECT name, ranks, layers, batches, time_limit, memory_limit FROM strategies" -header -column

costs:
	@sqlite3 /app/constraints.db "SELECT * FROM communication_costs" -header -column

requirements-%:
	@sqlite3 /app/constraints.db "SELECT category, requirement FROM strategy_requirements WHERE strategy_name='$*' ORDER BY req_order" -header -column

clean:
	rm -f /app/strategies.py
