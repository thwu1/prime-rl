FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y \
        python3 \
        python3-pip \
        llvm && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install lit==18.1.8

# Symlink FileCheck to a version-agnostic path
RUN for fc in /usr/lib/llvm-*/bin/FileCheck /usr/bin/FileCheck-*; do \
      if [ -f "$fc" ]; then ln -sf "$fc" /usr/bin/FileCheck && break; fi; \
    done && \
    FileCheck --version

# Install the IR optimizer tool
COPY tools/ /app/tools/
RUN chmod +x /app/tools/ir-opt

# Install input IR files for pass-behavior analysis
COPY inputs/ /app/inputs/

# Install analysis question schema
COPY analysis_schema.json /app/analysis_schema.json

# Create empty test directory (solver populates this)
RUN mkdir -p /app/tests

WORKDIR /app
