FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip wget && rm -rf /var/lib/apt/lists/*

RUN wget -q https://go.dev/dl/go1.22.10.linux-amd64.tar.gz -O /tmp/go.tar.gz && \
    tar -C /usr/local -xzf /tmp/go.tar.gz && \
    rm /tmp/go.tar.gz
ENV PATH="/usr/local/go/bin:${PATH}"
ENV GOPATH="/root/go"

WORKDIR /app

COPY spec.md /app/spec.md
COPY go_impl/ /app/go_impl/
COPY py_impl/ /app/py_impl/
