FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://github.com/FiloSottile/age/releases/download/v1.1.1/age-v1.1.1-linux-amd64.tar.gz -o /tmp/age.tar.gz && \
    tar -xzf /tmp/age.tar.gz -C /tmp && \
    cp /tmp/age/age /usr/local/bin/age && \
    cp /tmp/age/age-keygen /usr/local/bin/age-keygen && \
    chmod +x /usr/local/bin/age /usr/local/bin/age-keygen && \
    rm -rf /tmp/age /tmp/age.tar.gz

RUN pip3 install cryptography==42.0.5

COPY setup_corpus.py /tmp/setup_corpus.py
RUN python3 /tmp/setup_corpus.py && rm /tmp/setup_corpus.py

WORKDIR /app
