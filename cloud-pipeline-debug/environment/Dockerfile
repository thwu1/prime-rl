FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS data-builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install numpy==2.1.3 Pillow==11.1.0
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 Pillow==11.1.0

COPY --from=data-builder /app/data /app/data

RUN mkdir -p /app/pipeline /app/docs

COPY run_pipeline.sh /app/run_pipeline.sh
COPY calibrate.py /app/pipeline/calibrate.py
COPY classify.py /app/pipeline/classify.py
COPY validate.py /app/pipeline/validate.py
COPY score.py /app/pipeline/score.py
COPY format_spec.md /app/docs/FORMAT_SPEC.md

RUN chmod +x /app/run_pipeline.sh

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 numpy==2.1.3 Pillow==11.1.0
