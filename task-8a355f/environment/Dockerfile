FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/proposal-a /app/proposal-b /app/proposal-c /app/final-config

COPY security-requirements.yaml /app/security-requirements.yaml

COPY proposal-a/ /app/proposal-a/
COPY proposal-b/ /app/proposal-b/
COPY proposal-c/ /app/proposal-c/

WORKDIR /app
