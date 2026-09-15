FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip e2fsprogs && \
    rm -rf /var/lib/apt/lists/*

# Remove filesystem creation tools to prevent shortcuts;
# keep fsck.ext2, debugfs, dumpe2fs for diagnosis.
RUN rm -f /sbin/mke2fs /sbin/mkfs.ext2 /sbin/mkfs.ext3 /sbin/mkfs.ext4 \
         /usr/sbin/mke2fs /usr/sbin/mkfs.ext2 /usr/sbin/mkfs.ext3 /usr/sbin/mkfs.ext4 \
         /sbin/mkfs.ext4dev /usr/sbin/mkfs.ext4dev

RUN mkdir -p /app
WORKDIR /app
