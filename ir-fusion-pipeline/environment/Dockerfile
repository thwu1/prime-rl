FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y openjdk-21-jdk-headless python3 python3-pip curl wget && \
    rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64

# Install CPU-only torch first, then pyserini for sparse retrieval
RUN pip3 install --no-cache-dir torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu
RUN pip3 install --no-cache-dir pyserini==2.1.0

# Set up corpus, queries, and relevance judgments
COPY corpus.jsonl /app/corpus/docs.jsonl
COPY queries.tsv /app/queries.tsv
COPY qrels.txt /app/qrels.txt

# Build the initial (broken) pipeline artifacts that the agent must investigate
COPY setup_v1.sh /tmp/setup_v1.sh
RUN chmod +x /tmp/setup_v1.sh && /tmp/setup_v1.sh && rm /tmp/setup_v1.sh

# Add the colleague's pipeline log and evaluation report
COPY pipeline_log.txt /app/pipeline_log.txt
COPY report_v1.json /app/report_v1.json

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
