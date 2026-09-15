FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 pyyaml==6.0.2 pyzmq==26.2.0 -q

WORKDIR /app

COPY pipeline/ /app/pipeline/
COPY config.yaml /app/config.yaml
COPY schema.sql /app/schema.sql
COPY spec.md /app/spec.md
COPY paper_excerpt.md /app/paper_excerpt.md
COPY validate.py /app/validate.py
COPY server.py /app/server.py
COPY orchestrator_skeleton.py /app/orchestrator.py
RUN mkdir -p /app/reference
COPY reference.json /app/reference/expected.json
COPY generate_episodes.py /tmp/generate_episodes.py
RUN python3 /tmp/generate_episodes.py && rm /tmp/generate_episodes.py
RUN mkdir -p /app/output
