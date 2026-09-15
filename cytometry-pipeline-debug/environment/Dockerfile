FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    r-base \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*


COPY fcs_parser.R /app/fcs_parser.R
COPY compensation.R /app/compensation.R
COPY transforms.R /app/transforms.R
COPY gating.R /app/gating.R
COPY pipeline.R /app/pipeline.R

WORKDIR /app
