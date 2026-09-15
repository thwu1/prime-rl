FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip jq sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/docs /app/inputs

COPY app/mechcalc.py /app/mechcalc.py
COPY app/docs/bolt_connection.txt /app/docs/bolt_connection.txt
COPY app/docs/column_buckling.txt /app/docs/column_buckling.txt
COPY app/docs/vbelt_transmission.txt /app/docs/vbelt_transmission.txt
COPY app/inputs/standard_assembly.json /app/inputs/standard_assembly.json

RUN chmod +x /app/mechcalc.py

WORKDIR /app
