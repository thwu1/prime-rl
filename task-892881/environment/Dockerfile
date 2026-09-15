FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip swi-prolog && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/games

COPY games/switches.kif /app/games/switches.kif
COPY games/tictactoe.kif /app/games/tictactoe.kif
COPY games/connectfour.kif /app/games/connectfour.kif

WORKDIR /app
