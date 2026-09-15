
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y \
        python3 python3-pip \
        ruby ruby-dev \
        gcc g++ make \
        libseccomp-dev \
        auditd \
    && rm -rf /var/lib/apt/lists/*

RUN gem install seccomp-tools -v 1.6.0 --no-document

RUN mkdir -p /app

COPY generate_filter.py /tmp/generate_filter.py

RUN python3 /tmp/generate_filter.py /app/seccomp_filter.bpf && \
    rm /tmp/generate_filter.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
