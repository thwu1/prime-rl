FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN echo "wireshark-common wireshark-common/install-setuid boolean false" | debconf-set-selections && \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3 python3-pip tshark openssl && \
    rm -rf /var/lib/apt/lists/*

COPY gen_artifacts.py /tmp/gen_artifacts.py
RUN python3 /tmp/gen_artifacts.py && rm /tmp/gen_artifacts.py

RUN mkdir -p /app/certs && \
    openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
    -keyout /app/certs/key.pem -out /app/certs/cert.pem \
    -days 365 -nodes -subj '/CN=quic-test.example.com' \
    -set_serial 0x1234ABCD \
    -addext 'subjectAltName=DNS:quic-test.example.com,DNS:*.example.com' 2>/dev/null

WORKDIR /app
