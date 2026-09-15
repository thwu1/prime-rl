FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip jq && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==1.26.4 pandas==2.1.4 pyarrow==14.0.2 duckdb==0.10.3

COPY scene_flow_eval_reference.py /app/reference/scene_flow_eval.py
COPY detection_eval_reference.py /app/reference/detection_eval.py
COPY scoring_protocol.md /app/scoring_protocol.md
COPY submission_manifest.json /app/submissions/manifest.json
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

WORKDIR /app
