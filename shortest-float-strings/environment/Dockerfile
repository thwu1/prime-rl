FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    make \
    golang-go \
    sqlite3 \
    jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create challenge database
COPY init_db.py /tmp/init_db.py
RUN python3 /tmp/init_db.py && rm /tmp/init_db.py

# C converter sources and build system
RUN mkdir -p /app/src
COPY naive_convert.c /app/src/naive_convert.c
COPY fast_convert.c /app/src/fast_convert.c
COPY Makefile /app/Makefile

# Go round-trip verifier source with module init
COPY verify.go /app/verify.go
RUN cd /app && go mod init floatverify

# JSON output schema
COPY output_schema.json /app/output_schema.json
