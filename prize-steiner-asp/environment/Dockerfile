FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/docs /app/instances /app/legacy /app/checker

COPY README.md /app/README.md
COPY docs/problem.md /app/docs/problem.md
COPY docs/notes.md /app/docs/notes.md
COPY instances/inst_01.lp /app/instances/inst_01.lp
COPY instances/inst_02.lp /app/instances/inst_02.lp
COPY instances/inst_03.lp /app/instances/inst_03.lp
COPY instances/inst_04.lp /app/instances/inst_04.lp
COPY instances/test_manifest.json /app/instances/test_manifest.json
COPY legacy/steiner.lp /app/legacy/steiner.lp
COPY checker/verify.py /app/checker/verify.py

WORKDIR /app
