FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip python3-numpy python3-scipy && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Generate synthetic MCMC chain data
COPY generate_chains.py /tmp/generate_chains.py
RUN python3 /tmp/generate_chains.py && rm /tmp/generate_chains.py

# Copy task files (diagnostics module with bugs, analysis pipeline)
COPY diagnostics.py /app/diagnostics.py
COPY run_analysis.py /app/run_analysis.py

RUN mkdir -p /app/output
