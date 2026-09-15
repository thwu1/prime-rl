FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


# Install build tools and task dependencies
RUN apt-get update && \
    apt-get install -y build-essential cmake git python3-pip && \
    rm -rf /var/lib/apt/lists/*

# Download PHREEQC Version 3 source code
RUN git clone --depth 1 https://github.com/usgs-coupled/phreeqc3.git /app/phreeqc3_src

# Stage the broken model and field observations
COPY drain_model.pqi /app/drain_model.pqi
COPY field_observations.json /app/field_observations.json

WORKDIR /app
