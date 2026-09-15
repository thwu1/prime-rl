FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/agent_reports /app/results

COPY app_data/init_db.sql /tmp/init_db.sql
RUN sqlite3 /app/ground_truth.db < /tmp/init_db.sql && rm /tmp/init_db.sql

COPY app_data/paper_excerpt.md /app/paper_excerpt.md
COPY app_data/SPEC.md /app/SPEC.md
COPY app_data/evaluator_alpha.py /app/evaluator_alpha.py
COPY app_data/evaluator_beta.R /app/evaluator_beta.R
COPY app_data/agent_reports/agent_1.json /app/agent_reports/agent_1.json
COPY app_data/agent_reports/agent_2.json /app/agent_reports/agent_2.json
COPY app_data/agent_reports/agent_3.json /app/agent_reports/agent_3.json

WORKDIR /app
