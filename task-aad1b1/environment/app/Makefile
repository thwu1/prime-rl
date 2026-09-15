.PHONY: smoke bench profile profile-merge callgraph check-all

smoke:
	@python3 -c "from store.persistent_map import PersistentMap; m = PersistentMap().insert('a',1); assert m['a']==1; print('smoke: OK')"

bench:
	@python3 benchmarks/run_bench.py

profile:
	@python3 benchmarks/run_bench.py --profile

profile-merge:
	@python3 benchmarks/run_bench.py --profile-merge

callgraph:
	@python3 -m cProfile -o /app/profile.pstats benchmarks/profile_target.py
	@gprof2dot -f pstats /app/profile.pstats | dot -Tsvg -o /app/callgraph.svg
	@echo "Call graph written to /app/callgraph.svg"
	@python3 -c "import pstats; p = pstats.Stats('/app/profile.pstats'); p.sort_stats('cumulative').print_stats(20)"

check-all:
	@python3 benchmarks/run_bench.py --all
