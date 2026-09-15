FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive


RUN echo "wireshark-common wireshark-common/install-setuid boolean false" | debconf-set-selections && \
    apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    curl \
    netcat-openbsd \
    tcpdump \
    tshark \
    psmisc \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/docs /app/legacy /app/transcripts

COPY proxy_buggy.py /tmp/_build_proxy.py
RUN python3 -c "import zipfile;z=zipfile.ZipFile('/app/legacy/socks5d.pyz','w');z.write('/tmp/_build_proxy.py','__main__.py');z.close()" && rm /tmp/_build_proxy.py

COPY start_legacy.sh /app/legacy/start.sh
RUN chmod +x /app/legacy/start.sh

COPY transcripts/ /app/transcripts/
COPY acl.conf /app/acl.conf
COPY users.conf /app/users.conf
COPY rfc1928.txt /app/docs/rfc1928.txt
COPY rfc1929.txt /app/docs/rfc1929.txt

WORKDIR /app
