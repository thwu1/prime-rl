FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install ppbench - its puzzle engine (pzpr.js) requires Node.js which is not
# installed. The package source code and bundled data files are available for
# exploration in the pip installation directory.
RUN pip3 install ppbench==0.1.0

WORKDIR /app

COPY targets.json /app/targets.json
COPY pipeline.py /app/pipeline.py
