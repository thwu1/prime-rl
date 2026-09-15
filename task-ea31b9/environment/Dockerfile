FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 scipy==1.14.1 -q

WORKDIR /app
RUN mkdir -p /app/data /app/pipeline /app/output

COPY README.md /app/README.md
COPY experiments.json /app/data/experiments.json
COPY submissions.json /app/data/submissions.json
COPY validation.csv /app/data/validation.csv
COPY evaluator.py /app/pipeline/evaluator.py
