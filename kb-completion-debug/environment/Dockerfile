
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY app/term.py /app/term.py
COPY app/unify.py /app/unify.py
COPY app/ordering.py /app/ordering.py
COPY app/rewriting.py /app/rewriting.py
COPY app/completion.py /app/completion.py
COPY app/run_completion.py /app/run_completion.py
COPY app/kbo.py /app/kbo.py
COPY app/weight_finder.py /app/weight_finder.py

ENV PYTHONPATH=/app
WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 z3-solver==4.13.0.0
