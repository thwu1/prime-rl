FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    default-jre-headless \
    python3 \
    python3-pip \
    graphviz \
    gnuplot \
    curl \
    bzip2 \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sL https://github.com/jepsen-io/maelstrom/releases/download/v0.2.4/maelstrom.tar.bz2 -o /tmp/maelstrom.tar.bz2 && \
    tar xjf /tmp/maelstrom.tar.bz2 --no-same-owner -C /opt/ && \
    chmod +x /opt/maelstrom/maelstrom && \
    rm /tmp/maelstrom.tar.bz2

RUN git config --global user.email "test@test.com" && \
    git config --global user.name "test" && \
    git config --global --add safe.directory /opt/maelstrom && \
    cd /opt/maelstrom && git init && git add -A && git commit -m "init" --allow-empty

WORKDIR /app
