
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip curl unzip && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install duckdb==1.3.0 sqlglot==26.31.1 pyarrow==20.0.0 pandas==2.2.3

WORKDIR /app

COPY setup_db.py /app/setup_db.py
RUN python3 /app/setup_db.py

COPY decomposer_alpha.py /app/decomposer_alpha.py
COPY decomposer_beta.py /app/decomposer_beta.py
COPY stub_decomposer.py /app/decomposer.py
COPY run_pipeline.py /app/run_pipeline.py
