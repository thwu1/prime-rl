
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/pipeweave

COPY app/pipeweave/__init__.py /app/pipeweave/__init__.py
COPY app/pipeweave/config.py /app/pipeweave/config.py
COPY app/pipeweave/engine.py /app/pipeweave/engine.py
COPY app/pipeweave/transforms.py /app/pipeweave/transforms.py
COPY app/pipeweave/formatter.py /app/pipeweave/formatter.py
COPY app/pipeweave/schema.py /app/pipeweave/schema.py
COPY app/test_suite.py /app/test_suite.py

WORKDIR /app
