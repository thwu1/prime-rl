FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip g++ build-essential cmake sqlite3 && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/project/src /app/project/build

COPY problem.txt /app/problem.txt
COPY schema.md /app/SCHEMA.md
COPY CMakeLists.txt /app/project/CMakeLists.txt
COPY gen_db.py /tmp/gen_db.py

RUN python3 /tmp/gen_db.py && rm /tmp/gen_db.py

WORKDIR /app
