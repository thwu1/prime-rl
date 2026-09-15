FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip swi-prolog graphviz && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/games /app/prolog /app/graphs

COPY games/tictictoe.kif /app/games/tictictoe.kif
COPY games/connectfour.kif /app/games/connectfour.kif
COPY games/maze.kif /app/games/maze.kif

WORKDIR /app
