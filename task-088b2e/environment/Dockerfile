FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        make \
        jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/suites /app/pics /app/oracle

# Install buggy matcher as starting state (agent must diagnose and fix)
COPY matcher_buggy.py /app/matcher.py

# Pipeline orchestration and tools
COPY Makefile /app/Makefile
COPY conformance_runner.py /app/conformance_runner.py
COPY run_conformance.py /app/run_conformance.py
COPY ttcn3_validate.py /app/ttcn3_validate.py

# Engine test suites (JSON-IR format)
COPY suites/sip_registration.json /app/suites/sip_registration.json
COPY suites/diameter_rx.json /app/suites/diameter_rx.json

# Oracle test suites (template matching and verdict tests)
COPY oracle/matcher_tests.json /app/oracle/matcher_tests.json
COPY oracle/verdict_tests.json /app/oracle/verdict_tests.json

# PICS profiles
COPY pics/profile_a.json /app/pics/profile_a.json
COPY pics/profile_b.json /app/pics/profile_b.json

# Reference documentation
COPY reference.md /app/reference.md
COPY spec.md /app/spec.md
COPY ttcn3_reference.md /app/ttcn3_reference.md

WORKDIR /app
