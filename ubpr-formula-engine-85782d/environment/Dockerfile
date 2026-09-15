FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 jq && \
    rm -rf /var/lib/apt/lists/*


RUN mkdir -p /app/output

COPY data/formulas.json /app/formulas.json
COPY data/call_report_data.json /app/call_report_data.json
COPY data/xbrl_supplement.xml /app/xbrl_supplement.xml
COPY data/config.json /app/config.json

WORKDIR /app
