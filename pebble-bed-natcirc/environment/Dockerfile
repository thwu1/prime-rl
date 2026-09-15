FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gfortran \
    make \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 -q

COPY app/src/ /app/src/
COPY app/Makefile /app/Makefile
COPY app/reactor.toml /app/reactor.toml
COPY app/schema.sql /app/schema.sql
COPY app/natcirc_sim/ /app/natcirc_sim/
COPY app/validation/ /app/validation/

RUN cd /app && make
RUN sqlite3 /app/reactor.db < /app/schema.sql && rm /app/schema.sql

WORKDIR /app
