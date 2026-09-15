FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    g++ \
    make \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install CmdStanPy and compile CmdStan into /opt
RUN pip3 install cmdstanpy==1.2.4 && \
    install_cmdstan --dir /opt --cores 1

# Create stable symlink so CMDSTAN env var works across versions
RUN ln -sf $(ls -1d /opt/cmdstan-* | tail -1) /opt/cmdstan
ENV CMDSTAN=/opt/cmdstan

RUN mkdir -p /app/data /app/models /app/results
COPY data/hudson_bay_pelts.csv /app/data/hudson_bay_pelts.csv
WORKDIR /app
