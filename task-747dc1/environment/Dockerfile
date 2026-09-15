FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    g++ \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/fredbuf/include/fredbuf /app/fredbuf/src /app/fredbuf/docs

COPY fredbuf/README.md /app/fredbuf/README.md
COPY fredbuf/docs/piece_table.md /app/fredbuf/docs/piece_table.md
COPY fredbuf/docs/undo_tree.md /app/fredbuf/docs/undo_tree.md
COPY fredbuf/docs/diff.md /app/fredbuf/docs/diff.md
COPY fredbuf/docs/constraints.md /app/fredbuf/docs/constraints.md
COPY fredbuf/test/test_main.cpp /app/fredbuf/test/test_main.cpp
