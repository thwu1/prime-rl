FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Copy data generation assets
COPY setup_data.py /tmp/setup_data.py
COPY fhir_bundle.json /app/fhir_bundle.json

# Install pydicom (build-time only), generate DICOM files, then clean up
RUN pip3 install pydicom==2.4.4 && \
    python3 /tmp/setup_data.py && \
    pip3 uninstall pydicom -y && \
    rm /tmp/setup_data.py

WORKDIR /app
