FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV MTOOLS_SKIP_CHECK=1


RUN apt-get update && apt-get install -y \
    dosfstools \
    mtools \
    xxd \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY scripts/create_files.py /setup/create_files.py
COPY scripts/corrupt_image.py /setup/corrupt_image.py

RUN mkdir -p /app /expected && \
    python3 /setup/create_files.py /tmp/testfiles && \
    dd if=/dev/zero of=/tmp/clean.img bs=1M count=64 && \
    mkfs.vfat -F 32 -s 1 /tmp/clean.img && \
    mmd -i /tmp/clean.img ::docs && \
    mmd -i /tmp/clean.img ::logs && \
    mcopy -i /tmp/clean.img /tmp/testfiles/readme.txt :: && \
    mcopy -i /tmp/clean.img /tmp/testfiles/data.bin :: && \
    mcopy -i /tmp/clean.img /tmp/testfiles/config.ini :: && \
    mcopy -i /tmp/clean.img /tmp/testfiles/docs/notes.txt ::docs/ && \
    mcopy -i /tmp/clean.img /tmp/testfiles/docs/report.csv ::docs/ && \
    mcopy -i /tmp/clean.img /tmp/testfiles/logs/access.log ::logs/ && \
    cp -r /tmp/testfiles/* /expected/ && \
    python3 /setup/corrupt_image.py /tmp/clean.img /app/disk.img && \
    rm -rf /tmp/clean.img /tmp/testfiles /setup

WORKDIR /app
