FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV PYTHONPATH=/app


RUN apt-get update && apt-get install -y python3-pip libxml2-utils jq && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/idl
COPY app/interfaces.py /app/interfaces.py
COPY app/engine.py /app/engine.py
COPY app/run_checks.py /app/run_checks.py
COPY app/idl/messages.idl /app/idl/messages.idl
COPY app/idl/services.idl /app/idl/services.idl

WORKDIR /app
