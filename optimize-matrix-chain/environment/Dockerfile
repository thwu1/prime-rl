FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/problems /app/output

COPY spec.md /app/spec.md
COPY problems/problem_1.json /app/problems/problem_1.json
COPY problems/problem_2.json /app/problems/problem_2.json
COPY problems/problem_3.json /app/problems/problem_3.json
COPY problems/problem_4.json /app/problems/problem_4.json
COPY problems/problem_5.json /app/problems/problem_5.json

WORKDIR /app
