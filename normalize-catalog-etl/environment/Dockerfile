
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install sqlite-utils==3.38

RUN mkdir -p /app/feeds /app/output

COPY setup_data.py /app/setup_data.py
RUN python3 /app/setup_data.py && rm /app/setup_data.py

RUN python3 -c "import sqlite3; db=sqlite3.connect('/app/reference.db'); tabs=[r[0] for r in db.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]; print('Tables:', tabs); assert 'fx_corrections' in tabs, 'fx_corrections missing!'; assert 'fx_history' in tabs; assert 'supplier_directory' in tabs; assert 'supplier_aliases' in tabs; print('Verification OK')"

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
