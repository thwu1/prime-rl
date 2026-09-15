FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip gcc make sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/tools

COPY init_db.sql /tmp/init_db.sql
RUN sqlite3 /app/sudoku_archive.db < /tmp/init_db.sql && rm /tmp/init_db.sql

COPY sudoku_solver.c /app/tools/sudoku_solver.c
COPY Makefile /app/tools/Makefile

WORKDIR /app
