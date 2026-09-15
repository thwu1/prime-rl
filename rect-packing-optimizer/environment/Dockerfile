
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip g++ make sqlite3 jq bc && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY problem.md /app/problem.md
COPY scorer.py /app/scorer.py
COPY generate.py /app/generate.py
COPY evaluate.sh /app/evaluate.sh
COPY Makefile /app/Makefile
COPY solver_template.cpp /app/solver_template.cpp
COPY init_db.sql /app/init_db.sql

# Generate deterministic test cases
RUN mkdir -p /app/testcases && \
    python3 /app/generate.py 42 /app/testcases/case_0.txt && \
    python3 /app/generate.py 137 /app/testcases/case_1.txt && \
    python3 /app/generate.py 256 /app/testcases/case_2.txt && \
    python3 /app/generate.py 512 /app/testcases/case_3.txt && \
    python3 /app/generate.py 999 /app/testcases/case_4.txt

# Initialize results database with schema
RUN sqlite3 /app/results.db < /app/init_db.sql

RUN chmod +x /app/evaluate.sh
