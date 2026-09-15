
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    default-jdk-headless \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/games /app/reference

COPY games/sokoban.txt /app/games/sokoban.txt
COPY games/sokoban_lvl.txt /app/games/sokoban_lvl.txt
COPY games/zelda.txt /app/games/zelda.txt
COPY games/zelda_lvl.txt /app/games/zelda_lvl.txt
COPY games/boulderdash.txt /app/games/boulderdash.txt
COPY games/boulderdash_lvl.txt /app/games/boulderdash_lvl.txt

COPY reference/VGDLParser.java /app/reference/VGDLParser.java
COPY reference/ForwardModel.java /app/reference/ForwardModel.java
COPY reference/Game.java /app/reference/Game.java
COPY reference/Types.java /app/reference/Types.java

WORKDIR /app
