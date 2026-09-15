FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip jq sqlite3 && \
    rm -rf /var/lib/apt/lists/*

COPY patient_data/ /app/patient_data/
COPY pharmacology_init.sql /tmp/pharmacology_init.sql
RUN sqlite3 /app/pharmacology.db < /tmp/pharmacology_init.sql && rm /tmp/pharmacology_init.sql

RUN mkdir -p /app/output

WORKDIR /app
