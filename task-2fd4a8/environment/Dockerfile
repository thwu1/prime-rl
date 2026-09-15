FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS go-builder
RUN apt-get update && apt-get install -y golang-go && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /build
COPY xaes_tool.go /build/main.go
COPY go.mod /build/go.mod
WORKDIR /build
RUN CGO_ENABLED=0 go build -o /build/xaes_tool .

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS data-builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install pycryptodome==3.20.0

RUN mkdir -p /app/implementations/alpha /app/implementations/beta /app/implementations/gamma \
    /app/service /app/data /app/tests /app/vendor /app/docs

COPY impl_alpha_crypto.py /app/implementations/alpha/crypto.py
COPY impl_alpha_crypto.py /app/service/crypto.py
COPY impl_gamma_crypto.py /app/implementations/gamma/crypto.py

COPY service_keymanager.py /app/service/keymanager.py
COPY service_process_batch.py /app/service/process_batch.py
COPY service_config.json /app/service/config.json
COPY tests_test_roundtrip.py /app/tests/test_roundtrip.py
COPY vendor_interop_vectors.json /app/vendor/interop_vectors.json
COPY spec.txt /app/docs/spec.txt
COPY docs_README.md /app/docs/README.md

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip openssl xxd jq && rm -rf /var/lib/apt/lists/*

RUN pip3 install pycryptodome==3.20.0

COPY --from=data-builder /app/ /app/
COPY --from=go-builder /build/xaes_tool /app/implementations/beta/xaes_tool
RUN chmod +x /app/implementations/beta/xaes_tool

RUN mkdir -p /tests /solution /logs/verifier

WORKDIR /app
