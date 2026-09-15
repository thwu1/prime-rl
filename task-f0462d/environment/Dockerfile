# Stage 1: Generate synthetic gravity data (discarded in final image)
FROM python:3.12-slim AS data-generator
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py

# Stage 2: Task environment
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    gnuplot-nox \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY --from=data-generator /tmp/problem_config.json /app/problem_config.json
COPY --from=data-generator /tmp/observed_gravity.json /app/observed_gravity.json

WORKDIR /app
