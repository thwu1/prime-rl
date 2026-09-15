
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip g++ sqlite3 xxd && \
    rm -rf /var/lib/apt/lists/*

COPY polytool.cpp /tmp/polytool.cpp
RUN mkdir -p /app/bin && \
    g++ -O2 -std=c++17 -o /app/bin/polytool /tmp/polytool.cpp && \
    chmod +x /app/bin/polytool && \
    rm /tmp/polytool.cpp

COPY setup_workspace.py /tmp/setup_workspace.py
RUN python3 /tmp/setup_workspace.py && rm /tmp/setup_workspace.py

WORKDIR /app
