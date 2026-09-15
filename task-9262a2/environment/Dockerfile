FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip jq sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

COPY data/rubrics/ /app/data/rubrics/
COPY data/grades/ /app/data/grades/
COPY data/judge_eval/ /app/data/judge_eval/
COPY data/agreement/ /app/data/agreement/
COPY spec.md /app/spec.md
COPY buggy_engine.py /app/rubric_engine.py

WORKDIR /app
