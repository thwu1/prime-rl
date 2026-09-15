FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/header

COPY accelq.h /app/header/accelq.h
COPY interface_spec.txt /app/interface_spec.txt
COPY candidate_a.txt /app/candidate_a.txt
COPY candidate_b.txt /app/candidate_b.txt
COPY coverage_report.txt /app/coverage_report.txt

WORKDIR /app
