FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/baseline_results

COPY generate_matrix.py /app/generate_matrix.py
COPY baseline_solver.py /app/baseline_solver.py
COPY project_notes.txt /app/project_notes.txt
COPY baseline_results/ /app/baseline_results/

RUN python3 /app/generate_matrix.py

WORKDIR /app
