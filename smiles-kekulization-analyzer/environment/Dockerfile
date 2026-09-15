FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-rdkit \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/reference

COPY reference/training_set.jsonl /app/reference/training_set.jsonl
COPY reference/challenge_set.txt /app/reference/challenge_set.txt
COPY reference/notes.txt /app/reference/notes.txt
COPY reference/oracle.py /app/reference/oracle.py


WORKDIR /app
