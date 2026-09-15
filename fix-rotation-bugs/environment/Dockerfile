FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3

COPY lib_alpha.py /app/lib_alpha.py
COPY lib_beta.py /app/lib_beta.py
COPY lib_gamma.py /app/lib_gamma.py
COPY run_benchmark.py /app/run_benchmark.py
COPY pipeline.json /app/pipeline.json

COPY setup_benchmark.py /tmp/setup_benchmark.py
WORKDIR /app
RUN python3 /tmp/setup_benchmark.py && rm /tmp/setup_benchmark.py

COPY generate_logs.py /tmp/generate_logs.py
RUN python3 /tmp/generate_logs.py && rm /tmp/generate_logs.py
