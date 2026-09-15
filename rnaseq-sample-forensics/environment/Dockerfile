FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install numpy==2.1.3
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*
RUN pip3 install numpy==2.1.3 scipy==1.14.1 scikit-learn==1.5.2 pandas==2.2.3
COPY --from=builder /app/data /app/data
RUN mkdir -p /app/pipelines
COPY pipeline_a.py /app/pipelines/pipeline_a.py
COPY pipeline_b.py /app/pipelines/pipeline_b.py
COPY pipeline_c.py /app/pipelines/pipeline_c.py
COPY pipeline_d.py /app/pipelines/pipeline_d.py
WORKDIR /app
