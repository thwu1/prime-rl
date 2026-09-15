FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    g++ \
    make \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install CmdStan
ENV CMDSTAN=/opt/cmdstan
RUN wget -q https://github.com/stan-dev/cmdstan/releases/download/v2.34.1/cmdstan-2.34.1.tar.gz -O /tmp/cmdstan.tar.gz && \
    tar -xzf /tmp/cmdstan.tar.gz -C /opt && \
    mv /opt/cmdstan-2.34.1 /opt/cmdstan && \
    rm /tmp/cmdstan.tar.gz && \
    cd /opt/cmdstan && \
    make build -j$(nproc)

# Set O=0 for user model compilations (much faster compile, runtime speed irrelevant for small models)
RUN echo "O=0" > /opt/cmdstan/make/local

# Set up working directory
RUN mkdir -p /app

# Copy data generation script and broken model
COPY generate_data.py /tmp/generate_data.py
COPY broken_model.stan /app/model.stan

# Generate simulated data
RUN python3 /tmp/generate_data.py

# Pre-compile the broken model so the agent can run it immediately
RUN cd /opt/cmdstan && make /app/model

WORKDIR /app
