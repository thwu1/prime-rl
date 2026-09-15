FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    universal-ctags \
    patchutils \
    diffutils \
    && rm -rf /var/lib/apt/lists/*

COPY evaluator.py /app/evaluator.py
COPY data/cases/case_001 /app/data/cases/case_001
COPY data/cases/case_002 /app/data/cases/case_002
COPY data/cases/case_003 /app/data/cases/case_003
COPY data/cases/case_004 /app/data/cases/case_004
COPY data/cases/case_005 /app/data/cases/case_005
COPY data/cases/case_007 /app/data/cases/case_007

WORKDIR /app
