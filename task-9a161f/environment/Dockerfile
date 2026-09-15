
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc make strace && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/puzzles /app/solutions /app/generated /app/examples /app/tools

COPY tools/undead_tool.c /app/tools/undead_tool.c
COPY tools/Makefile /app/tools/Makefile
COPY puzzles/puzzle_1.txt /app/puzzles/puzzle_1.txt
COPY puzzles/puzzle_2.txt /app/puzzles/puzzle_2.txt
COPY puzzles/puzzle_3.txt /app/puzzles/puzzle_3.txt
COPY puzzles/puzzle_4.txt /app/puzzles/puzzle_4.txt
COPY examples/example_puzzle.txt /app/examples/example_puzzle.txt
COPY examples/example_solution.txt /app/examples/example_solution.txt

WORKDIR /app
