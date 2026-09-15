FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    make \
    xmlstarlet \
    && rm -rf /var/lib/apt/lists/*

COPY generate_data.py /tmp/generate_data.py
COPY data_format.md /app/data_format.md
COPY output_schema.md /app/output_schema.md
COPY Makefile /app/Makefile
COPY framework/ /app/framework/

RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

WORKDIR /app
