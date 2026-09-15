FROM golang:1.22-bookworm AS builder
WORKDIR /build
COPY services.go .
RUN go mod init svc && CGO_ENABLED=0 go build -ldflags="-s -w" -trimpath -o services .

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive


RUN echo "wireshark-common wireshark-common/install-setuid boolean false" | debconf-set-selections && \
    apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    curl \
    jq \
    xxd \
    openssl \
    tshark \
    nmap \
    ncat \
    tcpdump \
    socat \
    net-tools \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/services /usr/local/bin/services
COPY start_services.sh /app/start_services.sh
COPY analyst_notes.txt /tmp/analyst_notes.txt
RUN chmod +x /app/start_services.sh /usr/local/bin/services

RUN mkdir -p /app/certs && \
    openssl req -x509 -newkey rsa:2048 -keyout /app/certs/server.key \
    -out /app/certs/server.crt -days 365 -nodes \
    -subj "/CN=localhost/O=CryptoAuditSvc/C=US" 2>/dev/null

RUN FINGERPRINT=$(openssl x509 -in /app/certs/server.crt -fingerprint -sha256 -noout | cut -d= -f2 | tr -d :) && \
    openssl enc -aes-256-cbc -pbkdf2 -in /tmp/analyst_notes.txt -out /app/analyst_notes.enc -pass pass:$FINGERPRINT && \
    rm /tmp/analyst_notes.txt

RUN mkdir -p /var/run/svc /app
RUN echo '/app/start_services.sh 2>/dev/null' >> /root/.bashrc

WORKDIR /app
