FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN echo "wireshark-common wireshark-common/install-setuid boolean false" | debconf-set-selections && \
    DEBIAN_FRONTEND=noninteractive apt-get update && \
    apt-get install -y python3 python3-pip xxd bsdextrautils tshark && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/captures

COPY dicom_codec_buggy.py /app/dicom_codec.py
COPY gen_captures.py /app/gen_captures.py

WORKDIR /app
