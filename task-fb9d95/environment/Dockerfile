FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc libc-dev && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/shaders /app/generated

COPY spec.md /app/spec.md
COPY wgsl_parser.py /app/wgsl_parser.py
COPY c_codegen.py /app/c_codegen.py
COPY wgsl_layout.py /app/wgsl_layout.py
COPY reference_layouts.json /app/reference_layouts.json
COPY validation_log.txt /app/validation_log.txt
COPY shaders/ /app/shaders/

WORKDIR /app
