FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install numpy==2.1.3
COPY generate_traces.py /tmp/generate_traces.py
RUN mkdir -p /app && python3 /tmp/generate_traces.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/traces.trs /app/traces.trs
COPY format_spec.txt /app/format_spec.txt
COPY target_info.txt /app/target_info.txt
WORKDIR /app
