FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gnuplot-nox \
    && rm -rf /var/lib/apt/lists/*

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

COPY kernels.json /app/kernels.json
COPY stream_output.txt /app/stream_output.txt
COPY system_spec.json /app/system_spec.json

RUN mkdir -p /app/results

WORKDIR /app
