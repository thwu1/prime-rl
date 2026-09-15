FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip make git graphviz jq && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install gprof2dot==2024.6.6

# --- Stage 1: Clean working implementation ---
COPY app/store/__init__.py /app/store/__init__.py
COPY versions/v0_clean.py /app/store/persistent_map.py
COPY app/benchmarks/ /app/benchmarks/
COPY app/Makefile /app/Makefile
COPY app/README.md /app/README.md

WORKDIR /app

RUN git init && \
    git config user.email "dev@store.internal" && \
    git config user.name "Store Team" && \
    git add -A && \
    git commit -m "feat: CHAMP persistent map with dual-bitmap trie and diagnostics"

# --- Stage 2: Insert + delete regressions introduced ---
COPY versions/v1_partial.py /app/store/persistent_map.py
RUN git add -A && \
    git commit -m "perf: optimize entry creation and simplify delete path"

# --- Stage 3: Diff regressions introduced ---
COPY app/store/persistent_map.py /app/store/persistent_map.py
RUN git add -A && \
    git commit -m "perf: streamline diff traversal and collision comparison"

# --- Stage 4: Issue tracker added ---
COPY app/issues/ /app/issues/
RUN git add -A && \
    git commit -m "docs: production bug reports and merge feature request (issues 001-004)"
