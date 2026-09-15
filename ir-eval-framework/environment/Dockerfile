FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install scipy==1.14.1

WORKDIR /app
RUN mkdir -p /app/data/runs

COPY generate_data.py /tmp/generate_data.py
COPY ms_marco_eval.py /app/ms_marco_eval.py
COPY pipeline.py /app/pipeline.py

RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py
RUN python3 /app/pipeline.py --qrels /app/data/qrels.tsv --runs /app/data/runs/ --output /app/pipeline_output.json
