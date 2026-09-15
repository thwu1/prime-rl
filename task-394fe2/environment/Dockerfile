FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS data-gen
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==1.26.4

COPY --from=data-gen /opt/crumb_eval/ /opt/crumb_eval/

COPY protocol.md /opt/crumb_eval/protocol.md
COPY pipeline.py /opt/crumb_eval/pipeline.py

RUN mkdir -p /opt/crumb_eval/output && python3 /opt/crumb_eval/pipeline.py

WORKDIR /app
