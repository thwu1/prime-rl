FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip graphviz && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3

RUN mkdir -p /app/causal_lib

COPY scaffold/__init__.py /app/causal_lib/__init__.py
COPY scaffold/variable.py /app/causal_lib/variable.py
COPY scaffold/scm.py /app/causal_lib/scm.py
COPY scaffold/query_engine.py /app/causal_lib/query_engine.py
COPY scaffold/graph_analysis.py /app/causal_lib/graph_analysis.py
COPY scaffold/graph.yaml /app/graph.yaml
COPY scaffold/mechanisms.py /app/mechanisms.py
COPY scaffold/queries.yaml /app/queries.yaml
COPY scaffold/schema.sql /app/schema.sql
COPY scaffold/specifications.md /app/specifications.md

WORKDIR /app
