
# Stage 1: Generate buggy vendor submissions
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install pycryptodome==3.21.0

COPY aes_cbc_prompt.json /tmp/aes_cbc_prompt.json
COPY sha256_prompt.json /tmp/sha256_prompt.json
COPY generate_vendors.py /tmp/generate_vendors.py

RUN python3 /tmp/generate_vendors.py

# Stage 2: Clean task environment (no generation scripts or crypto libs)
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip openssl && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/prompts /app/specs /app/results /app/vendor_submissions

COPY aes_cbc_prompt.json /app/prompts/aes_cbc_prompt.json
COPY sha256_prompt.json /app/prompts/sha256_prompt.json
COPY acvp_test_procedures.md /app/specs/acvp_test_procedures.md

COPY --from=builder /tmp/vendor_alpha/ /app/vendor_submissions/alpha/
COPY --from=builder /tmp/vendor_beta/ /app/vendor_submissions/beta/
COPY --from=builder /tmp/vendor_gamma/ /app/vendor_submissions/gamma/

WORKDIR /app
