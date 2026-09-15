
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV LC_COLLATE=C

RUN apt-get update && \
    apt-get install -y python3 python3-pip xxd strace iproute2 curl socat procps && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/binaudit /app/samples /app/output \
    /opt/binaudit-gateway /etc/binaudit /var/lib/binaudit

COPY binaudit.py /app/binaudit/binaudit.py
COPY format_spec.txt /app/binaudit/format_spec.txt

COPY create_example.py /tmp/create_example.py
RUN python3 /tmp/create_example.py && rm /tmp/create_example.py

COPY gateway.py /opt/binaudit-gateway/server.py
COPY gateway.conf /etc/binaudit/gateway.conf

# Pristine copy for test verification (prevents tampering)
RUN cp /app/binaudit/binaudit.py /usr/local/share/binaudit_original.py

# Generate credential from hash so it is not a static string in the layer
RUN python3 -c "\
import hashlib; \
h = hashlib.sha256(b'binaudit-gateway-api-credential').hexdigest()[:40]; \
print(f'CRED_{h}')" > /var/lib/binaudit/credential.key

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /app

ENTRYPOINT ["/entrypoint.sh"]
CMD ["sleep", "infinity"]
