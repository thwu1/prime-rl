FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 jq make && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install pyyaml==6.0.2

RUN mkdir -p /app/src /app/logs /app/reference

COPY setup_db.py /tmp/setup_db.py
RUN python3 /tmp/setup_db.py && rm /tmp/setup_db.py

COPY config.yaml /app/config.yaml
COPY Makefile /app/Makefile
COPY src/__init__.py /app/src/__init__.py
COPY src/data_loader.py /app/src/data_loader.py
COPY src/qubit_encoding.py /app/src/qubit_encoding.py
COPY src/analysis.py /app/src/analysis.py
COPY src/pipeline.py /app/src/pipeline.py
COPY logs/previous_run.log /app/logs/previous_run.log
COPY reference/known_result.txt /app/reference/known_result.txt

ENV PYTHONPATH=/app/src

WORKDIR /app
