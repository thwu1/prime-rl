FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install duckdb==1.1.3

COPY setup_db.py /setup/setup_db.py
COPY requirements.md /app/requirements.md
COPY reports/ /app/reports/

RUN mkdir -p /app/corrected_reports

RUN python3 -c "import duckdb; con = duckdb.connect(); con.execute('INSTALL tpch'); con.close()"

RUN python3 /setup/setup_db.py

RUN rm -rf /setup

WORKDIR /app
