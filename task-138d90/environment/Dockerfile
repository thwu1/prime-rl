FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    git \
    make \
    && rm -rf /var/lib/apt/lists/*

# Install runtime dependencies used by the evaluation pipeline
RUN pip3 install numpy==2.1.3 pyarrow==17.0.0 pyyaml==6.0.2 -q

# Create directory structure
RUN mkdir -p /app/pipeline /app/config /app/data

# Copy pipeline source code
COPY pipeline_init.py /app/pipeline/__init__.py
COPY pipeline_config.py /app/pipeline/config.py
COPY pipeline_preprocessing.py /app/pipeline/preprocessing.py
COPY pipeline_assignment.py /app/pipeline/assignment.py
COPY pipeline_metrics.py /app/pipeline/metrics.py
COPY run_eval.py /app/run_eval.py

# Copy configuration files
COPY config_main.toml /app/config/main.toml
COPY config_overrides.yaml /app/config/overrides.yaml

# Copy evaluation specification
COPY spec.md /app/spec.md

# Copy Makefile for pipeline orchestration
COPY Makefile /app/Makefile

# Generate synthetic evaluation data
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

# Initialize git repository with development history
COPY setup_repo.sh /tmp/setup_repo.sh
RUN chmod +x /tmp/setup_repo.sh && /tmp/setup_repo.sh && rm /tmp/setup_repo.sh

WORKDIR /app
