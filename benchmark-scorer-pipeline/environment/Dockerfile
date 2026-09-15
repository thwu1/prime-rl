
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    jq \
    make \
    miller \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install csvkit==2.0.0

RUN mkdir -p /app/output /app/pipelines /app/outputs /app/data/csv /app/data/ndjson /tmp/benchdata/results

COPY data/papers.json /tmp/benchdata/papers.json
COPY data/snippets.json /tmp/benchdata/snippets.json
COPY data/models.json /tmp/benchdata/models.json
COPY data/results/aurora-72b.json /tmp/benchdata/results/aurora-72b.json
COPY data/results/blazeai-13b.json /tmp/benchdata/results/blazeai-13b.json
COPY data/results/cognet-pro.json /tmp/benchdata/results/cognet-pro.json
COPY data/results/deepmind-ultra.json /tmp/benchdata/results/deepmind-ultra.json
COPY data/results/etheron-7b.json /tmp/benchdata/results/etheron-7b.json
COPY data/results/frontier-max.json /tmp/benchdata/results/frontier-max.json
COPY setup_db.py /tmp/setup_db.py
COPY export_data.sh /tmp/export_data.sh

RUN chmod +x /tmp/export_data.sh && python3 /tmp/setup_db.py && /tmp/export_data.sh && rm -rf /tmp/benchdata /tmp/setup_db.py /tmp/export_data.sh

COPY pipeline_alpha.py /app/pipelines/alpha.py
COPY pipeline_beta.py /app/pipelines/beta.py
COPY pipeline_gamma.py /app/pipelines/gamma.py
COPY pipeline_buggy.py /app/pipeline.py
COPY requirements.md /app/METHODOLOGY.md
COPY Makefile /app/Makefile

RUN python3 /app/pipelines/alpha.py \
    && python3 /app/pipelines/beta.py \
    && python3 /app/pipelines/gamma.py \
    && python3 /app/pipeline.py

WORKDIR /app
