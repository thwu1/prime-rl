FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 jq xxd && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY setup_wal.py /tmp/setup_wal.py
COPY setup_pages.py /tmp/setup_pages.py
COPY crash_report.json /tmp/crash_report.json
COPY page_format.md /tmp/page_format.md
COPY system_info.txt /tmp/system_info.txt
COPY setup_diagnostics.py /tmp/setup_diagnostics.py
COPY schema.md /app/schema.md

RUN python3 /tmp/setup_wal.py && python3 /tmp/setup_pages.py && python3 /tmp/setup_diagnostics.py && rm -f /tmp/setup_*.py /tmp/crash_report.json /tmp/page_format.md /tmp/system_info.txt

WORKDIR /app
