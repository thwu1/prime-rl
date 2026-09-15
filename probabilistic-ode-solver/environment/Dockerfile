FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 gnuplot libhdf5-dev pkg-config && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/results

COPY problem.json /app/problem.json

WORKDIR /app
