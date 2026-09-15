FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip python3 sqlite3 gawk && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/pipeline

COPY data/ontology.obo /app/data/ontology.obo
COPY data/annotations.hpoa /app/data/annotations.hpoa

COPY pipeline/schema.sql /app/pipeline/schema.sql
COPY pipeline/obo_graph.py /app/pipeline/obo_graph.py
COPY pipeline/process_annotations.awk /app/pipeline/process_annotations.awk
COPY pipeline/load_annotations.sh /app/pipeline/load_annotations.sh
COPY pipeline/similarity.py /app/pipeline/similarity.py
COPY pipeline/config.json /app/pipeline/config.json
COPY pipeline/run_pipeline.sh /app/pipeline/run_pipeline.sh

RUN chmod +x /app/pipeline/run_pipeline.sh /app/pipeline/load_annotations.sh

WORKDIR /app
