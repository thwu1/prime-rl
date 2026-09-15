FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/programs /app/results

COPY generate_programs.py /tmp/generate_programs.py
RUN python3 /tmp/generate_programs.py && rm /tmp/generate_programs.py

WORKDIR /app
