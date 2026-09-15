FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/site_data /app/reference

COPY mw1_arsenic.csv /app/site_data/mw1_arsenic.csv
COPY mw2_tce.csv /app/site_data/mw2_tce.csv
COPY mw3_lead.csv /app/site_data/mw3_lead.csv
COPY mw5_chromium.csv /app/site_data/mw5_chromium.csv

COPY create_benzene_db.sql /tmp/create_benzene_db.sql
RUN sqlite3 /app/site_data/mw4_benzene.db < /tmp/create_benzene_db.sql && rm /tmp/create_benzene_db.sql

COPY proucl_methodology.md /app/reference/proucl_methodology.md
COPY decision_flowchart.txt /app/reference/decision_flowchart.txt

COPY preliminary_report.json /app/preliminary_report.json

WORKDIR /app
