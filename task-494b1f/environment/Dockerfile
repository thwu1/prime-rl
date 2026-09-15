FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip patch sqlite3 diffutils make xxd && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/output/snapshots /app/output/diffs

COPY piece_table_stub.py /app/piece_table.py
COPY journal_format.txt /app/journal_format.txt
COPY gen_journal.py /tmp/gen_journal.py
RUN python3 /tmp/gen_journal.py > /app/journal.bin && rm /tmp/gen_journal.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
