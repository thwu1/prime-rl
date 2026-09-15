FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install numpy==2.1.3 -q

COPY setup_data.py /tmp/setup_data.py
COPY buggy_evaluator.py /tmp/buggy_evaluator.py
COPY config.toml /tmp/config.toml
COPY run_pipeline.sh /tmp/run_pipeline.sh
COPY evaluation_notes.md /tmp/evaluation_notes.md
COPY validation_report.md /tmp/validation_report.md

RUN python3 /tmp/setup_data.py && \
    mkdir -p /app/evaluator /app/docs && \
    cp /tmp/buggy_evaluator.py /app/evaluator/evaluate.py && \
    cp /tmp/config.toml /app/evaluator/config.toml && \
    cp /tmp/run_pipeline.sh /app/evaluator/run_pipeline.sh && \
    chmod +x /app/evaluator/run_pipeline.sh && \
    cp /tmp/evaluation_notes.md /app/docs/evaluation_notes.md && \
    cp /tmp/validation_report.md /app/docs/validation_report.md && \
    rm -rf /tmp/*.py /tmp/*.toml /tmp/*.sh /tmp/*.md

WORKDIR /app
