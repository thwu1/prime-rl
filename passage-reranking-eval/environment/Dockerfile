FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data/runs /app/pipeline/output /app/output

COPY setup_data.py /tmp/setup_data.py
COPY ms_marco_eval.py /app/data/ms_marco_eval.py
COPY pipeline_tokenizer.py /app/pipeline/tokenizer.py
COPY pipeline_index.py /app/pipeline/index.py
COPY pipeline_bm25.py /app/pipeline/bm25.py
COPY pipeline_run.py /app/pipeline/run_pipeline.py

RUN python3 /tmp/setup_data.py && rm /tmp/setup_data.py

RUN cd /app && python3 pipeline/run_pipeline.py > /app/pipeline/last_run.log 2>&1; exit 0

WORKDIR /app
