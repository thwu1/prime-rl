FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    openssl \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Create PKI directory structure
RUN mkdir -p /app/pki/root-ca/private \
    /app/pki/root-ca/certs \
    /app/pki/root-ca/crl \
    /app/pki/root-ca/newcerts \
    /app/pki/intermediate-ca/private \
    /app/pki/intermediate-ca/certs \
    /app/pki/intermediate-ca/crl \
    /app/pki/intermediate-ca/newcerts \
    /app/pki/intermediate-ca/csr

RUN chmod 700 /app/pki/root-ca/private /app/pki/intermediate-ca/private

# Copy broken configuration files (contain deliberate errors)
COPY root-ca-openssl.cnf /app/pki/root-ca/openssl.cnf
COPY intermediate-ca-openssl.cnf /app/pki/intermediate-ca/openssl.cnf

# Generate deployment-specific parameters (audit stamp, server IP) and requirements
COPY gen_env.py /tmp/gen_env.py
RUN python3 /tmp/gen_env.py && rm /tmp/gen_env.py

# Initialize Root CA database files
RUN touch /app/pki/root-ca/index.txt && \
    echo 'unique_subject = yes' > /app/pki/root-ca/index.txt.attr && \
    echo '1000' > /app/pki/root-ca/serial && \
    echo '1000' > /app/pki/root-ca/crlnumber

# Initialize Intermediate CA database files
RUN touch /app/pki/intermediate-ca/index.txt && \
    echo 'unique_subject = yes' > /app/pki/intermediate-ca/index.txt.attr && \
    echo '2000' > /app/pki/intermediate-ca/serial && \
    echo '2000' > /app/pki/intermediate-ca/crlnumber

# Generate Root CA private key (EC P-384)
RUN openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:secp384r1 \
    -out /app/pki/root-ca/private/root-ca.key && \
    chmod 400 /app/pki/root-ca/private/root-ca.key

WORKDIR /app
