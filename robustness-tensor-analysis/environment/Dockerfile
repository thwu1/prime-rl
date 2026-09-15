FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 pyyaml==6.0.2 -q

RUN mkdir -p /app/pipeline/stages /app/config /app/data /app/output

COPY taxonomy.json /app/config/taxonomy.json
COPY analysis_config.yaml /app/config/analysis.yaml
COPY workflow.yaml /app/config/workflow.yaml

COPY run.py /app/pipeline/run.py
COPY db.py /app/pipeline/db.py
COPY stages_init.py /app/pipeline/stages/__init__.py
COPY stages_confidence.py /app/pipeline/stages/confidence.py
COPY stages_effects.py /app/pipeline/stages/effects.py
COPY stages_decomposition.py /app/pipeline/stages/decomposition.py
COPY stages_robustness.py /app/pipeline/stages/robustness.py
COPY stages_interactions.py /app/pipeline/stages/interactions.py
COPY stages_ranking.py /app/pipeline/stages/ranking.py
COPY stages_significance.py /app/pipeline/stages/significance.py

COPY generate_db.py /tmp/generate_db.py
RUN python3 /tmp/generate_db.py && rm /tmp/generate_db.py

WORKDIR /app
