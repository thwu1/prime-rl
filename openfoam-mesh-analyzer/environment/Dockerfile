FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/case/system /app/pipeline

COPY blockMeshDict /app/case/system/blockMeshDict
COPY cht_params.json /app/case/cht_params.json
COPY pipeline/parser.py /app/pipeline/parser.py
COPY pipeline/analyzer.py /app/pipeline/analyzer.py
COPY pipeline/cht_solver.py /app/pipeline/cht_solver.py
COPY pipeline/run.py /app/pipeline/run.py
COPY validate.py /app/validate.py

RUN touch /app/pipeline/__init__.py

WORKDIR /app
