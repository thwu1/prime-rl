FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install rdkit==2024.3.5 numpy==1.26.4 pandas==2.2.3 pyyaml==6.0.2

RUN mkdir -p /app/project/data /app/project/config /app/project/docs /app/results

COPY structures.csv /app/project/data/structures.csv
COPY bioactivity.tsv /app/project/data/bioactivity.tsv
COPY exclusions.json /app/project/data/exclusions.json
COPY pipeline.yaml /app/project/config/pipeline.yaml
COPY methodology.md /app/project/docs/methodology.md
COPY project_readme.md /app/project/README.md

WORKDIR /app
