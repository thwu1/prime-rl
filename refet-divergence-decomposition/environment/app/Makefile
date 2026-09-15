CC = gcc
CFLAGS = -shared -fPIC
LDFLAGS = -lm

.PHONY: validate smoke lib preprocess clean diagnose-daily diagnose-hourly diagnose-decomp

lib:
	mkdir -p /app/lib
	$(CC) $(CFLAGS) -o /app/lib/libatmos.so /app/src/atmos.c $(LDFLAGS)

preprocess:
	bash /app/scripts/preprocess.sh

smoke: lib
	@python3 -c "from et_engine import compute_daily; print('Import OK')"

validate: lib preprocess
	@python3 /app/validate_runner.py all

diagnose-daily: lib preprocess
	@python3 /app/validate_runner.py daily

diagnose-hourly: lib preprocess
	@python3 /app/validate_runner.py hourly

diagnose-decomp: lib preprocess
	@python3 /app/validate_runner.py decomp

clean:
	rm -f /app/lib/libatmos.so /app/data/station.json
