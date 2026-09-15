FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip python3 && rm -rf /var/lib/apt/lists/*

COPY raw_data/ /app/raw_data/
COPY schema/ /app/schema/
RUN mkdir -p /app/sdtm_output

WORKDIR /app
