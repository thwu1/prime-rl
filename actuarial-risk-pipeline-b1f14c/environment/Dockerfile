FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y r-base r-base-dev build-essential python3-pip && \
    rm -rf /var/lib/apt/lists/*


COPY risk_pipeline.R /app/risk_pipeline.R
COPY run_pipeline.R /app/run_pipeline.R

WORKDIR /app
