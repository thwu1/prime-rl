FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip jq sqlite3 && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app /tests /solution /logs/verifier

COPY streaming.py /app/streaming.py
COPY pipeline.py /app/pipeline.py
COPY savepoint.py /app/savepoint.py
COPY setup_checkpoint.py /app/setup_checkpoint.py
COPY pipeline-ctl /app/pipeline-ctl

RUN chmod +x /app/pipeline-ctl && \
    ln -s /app/pipeline-ctl /usr/local/bin/pipeline-ctl

WORKDIR /app
RUN python3 setup_checkpoint.py
