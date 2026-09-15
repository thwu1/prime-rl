SHELL := /bin/bash

.PHONY: run trace diff bisect-test

run:
	@python3 run.py

trace:
	@STYLE_DEBUG=1 python3 run.py > /dev/null

diff:
	@python3 run.py 2>/dev/null > /tmp/.engine_current.json && \
	jq -S '.' .expected_output.json > /tmp/.engine_expected.json && \
	jq -S '.' /tmp/.engine_current.json > /tmp/.engine_actual.json && \
	diff /tmp/.engine_expected.json /tmp/.engine_actual.json; \
	EXIT=$$?; rm -f /tmp/.engine_current.json /tmp/.engine_expected.json /tmp/.engine_actual.json; exit $$EXIT

bisect-test:
	@python3 run.py 2>/dev/null > /tmp/.bisect_out.json && \
	jq -S '.' .expected_output.json > /tmp/.bisect_exp.json && \
	jq -S '.' /tmp/.bisect_out.json > /tmp/.bisect_cur.json && \
	diff -q /tmp/.bisect_exp.json /tmp/.bisect_cur.json > /dev/null 2>&1; \
	EXIT=$$?; rm -f /tmp/.bisect_out.json /tmp/.bisect_exp.json /tmp/.bisect_cur.json; exit $$EXIT
