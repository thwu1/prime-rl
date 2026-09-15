FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

# pytrec_eval is a task dependency: the evaluation script imports it
RUN pip3 install numpy==2.1.3 pytrec-eval-terrier==0.5.6

COPY setup/ /app/setup/
RUN python3 /app/setup/generate_data.py

COPY src/ /app/src/
COPY config.json /app/config.json

WORKDIR /app
