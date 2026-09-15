
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        gcc \
        make \
        libc6-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/spec /app/framework /app/pipeline /app/tools/src /app/output

COPY brdf_spec.md /app/spec/brdf_spec.md
COPY reference.md /app/spec/reference.md

COPY lut_io.py /app/framework/lut_io.py

COPY dfg_generator_buggy.py /app/pipeline/dfg_generator.py
COPY brdf_buggy.py /app/pipeline/brdf.py
COPY sampler.py /app/pipeline/sampler.py
COPY pipeline_config.json /app/pipeline/pipeline_config.json

COPY dfg_reference.c /app/tools/src/dfg_reference.c
COPY lut_compare.c /app/tools/src/lut_compare.c
COPY Makefile /app/tools/Makefile

WORKDIR /app
