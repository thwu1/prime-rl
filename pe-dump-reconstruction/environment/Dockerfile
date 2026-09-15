FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 radare2 yara && rm -rf /var/lib/apt/lists/*

COPY output_schema.json /app/output_schema.json
COPY generate_pe.py /tmp/generate_pe.py
RUN python3 /tmp/generate_pe.py && rm /tmp/generate_pe.py

WORKDIR /app
