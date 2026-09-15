.PHONY: test stress clean check-redis redis-ready

redis-ready:
	@redis-cli ping > /dev/null 2>&1 || (redis-server --daemonize yes --save "" --appendonly no && sleep 0.5)

.deps_installed:
	pip3 install pytest==8.3.4 hypothesis==6.100.0 redis==5.0.3 -q
	@touch .deps_installed

test: redis-ready .deps_installed
	python3 -m pytest /tests/test_state.py -v

stress: redis-ready .deps_installed
	python3 -m pytest /tests/test_state.py -v -k "Concurrent or Property"

check-redis:
	redis-cli ping
	redis-cli info keyspace

clean:
	rm -f .deps_installed
	redis-cli shutdown nosave 2>/dev/null || true
