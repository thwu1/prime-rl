FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3-pip \
    redis-tools \
    wget \
    curl \
    libicu-dev \
    && rm -rf /var/lib/apt/lists/*

# Install .NET 8 SDK via official install script
RUN curl -sSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh && \
    chmod +x /tmp/dotnet-install.sh && \
    /tmp/dotnet-install.sh --channel 8.0 --install-dir /usr/share/dotnet && \
    ln -sf /usr/share/dotnet/dotnet /usr/bin/dotnet && \
    rm /tmp/dotnet-install.sh

ENV DOTNET_ROOT=/usr/share/dotnet
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1

# Install garnet-server dotnet tool to a specific path (avoids $HOME/.dotnet/tools issues)
RUN dotnet tool install garnet-server --version 1.0.45 --tool-path /opt/garnet-tool

# Ensure garnet-server is on PATH before any other entries
ENV PATH="/opt/garnet-tool:/usr/share/dotnet:${PATH}"

# Verify garnet-server is accessible on PATH
RUN which garnet-server

# Copy Garnet configuration and initialization scripts
COPY garnet.conf /opt/garnet/garnet.conf
COPY init_cluster.sh /opt/garnet/init_cluster.sh
COPY seed_keys.py /opt/garnet/seed_keys.py
RUN chmod +x /opt/garnet/init_cluster.sh

WORKDIR /app
