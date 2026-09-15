FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


# Disable LeakSanitizer — it cannot run under ptrace/container runtimes
ENV ASAN_OPTIONS=detect_leaks=0

RUN apt-get update && apt-get install -y gcc g++ make python3-pip && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY src/kvstore.c /app/src/kvstore.c
COPY Makefile /app/Makefile
COPY setup_tests.py /tmp/setup_tests.py

RUN cd /app && make

RUN python3 /tmp/setup_tests.py

RUN mkdir -p /app/asan_reports
RUN /app/kvstore /app/poc/poc1.cfg > /dev/null 2> /app/asan_reports/report1.txt || true
RUN /app/kvstore /app/poc/poc2.cfg > /dev/null 2> /app/asan_reports/report2.txt || true
RUN /app/kvstore /app/poc/poc3.cfg > /dev/null 2> /app/asan_reports/report3.txt || true
RUN /app/kvstore /app/poc/poc4.cfg > /dev/null 2> /app/asan_reports/report4.txt || true

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
