FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip jq && rm -rf /var/lib/apt/lists/*

COPY map_matrix.csv /app/map_matrix.csv
COPY generate_data.py /app/generate_data.py
COPY evaluate_draft.py /app/evaluate_draft.py

WORKDIR /app
