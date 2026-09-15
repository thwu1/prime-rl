
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    build-essential \
    gdb \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3

RUN mkdir -p /app/autograd/numpy /app/autograd/csrc

# --- Core framework files (working) ---
COPY tracer.py /app/autograd/tracer.py
COPY core.py /app/autograd/core.py
COPY differential_operators.py /app/autograd/differential_operators.py

# --- Utility with toposort (has traversal issue) ---
COPY util.py /app/autograd/util.py

# --- Package init (imports custom_logsumexp) ---
COPY autograd_init.py /app/autograd/__init__.py

# --- C-accelerated custom operations wrapper (path issue) ---
COPY custom_ops_wrapper.py /app/autograd/custom_ops_wrapper.py

# --- NumPy subpackage ---
COPY numpy_wrapper.py /app/autograd/numpy/numpy_wrapper.py
COPY numpy_boxes.py /app/autograd/numpy/numpy_boxes.py
COPY numpy_vjps.py /app/autograd/numpy/numpy_vjps.py
COPY numpy_init.py /app/autograd/numpy/__init__.py

# --- C source and build system (Makefile has issues) ---
COPY custom_ops.c /app/autograd/csrc/custom_ops.c
COPY csrc_Makefile /app/autograd/csrc/Makefile

WORKDIR /app
