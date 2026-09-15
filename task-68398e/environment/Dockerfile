FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    curl \
    python3-pip \
    jq \
    openssl \
    && rm -rf /var/lib/apt/lists/*

# Install etcd binaries
RUN ETCD_VER=v3.5.17 && \
    ARCH=$(uname -m) && \
    case $ARCH in x86_64) PLATFORM=linux-amd64;; aarch64) PLATFORM=linux-arm64;; *) PLATFORM=linux-amd64;; esac && \
    curl -L https://github.com/etcd-io/etcd/releases/download/${ETCD_VER}/etcd-${ETCD_VER}-${PLATFORM}.tar.gz -o /tmp/etcd.tar.gz && \
    tar xzf /tmp/etcd.tar.gz -C /tmp && \
    mv /tmp/etcd-${ETCD_VER}-${PLATFORM}/etcd /usr/local/bin/ && \
    mv /tmp/etcd-${ETCD_VER}-${PLATFORM}/etcdctl /usr/local/bin/ && \
    mv /tmp/etcd-${ETCD_VER}-${PLATFORM}/etcdutl /usr/local/bin/ && \
    rm -rf /tmp/etcd*

# Create directory structure
RUN mkdir -p /app/pki /app/pki-fixed /app/manifests /app/manifests-fixed \
    /app/etcd /app/kubeconfig /app/rbac

# Copy broken manifests
COPY kube-apiserver.yaml /app/manifests/kube-apiserver.yaml
COPY kube-scheduler.yaml /app/manifests/kube-scheduler.yaml
COPY kube-controller-manager.yaml /app/manifests/kube-controller-manager.yaml
COPY etcd.yaml /app/manifests/etcd.yaml

# Copy RBAC requirements
COPY rbac-requirements.txt /app/rbac/requirements.txt

# Copy and run PKI setup (generates broken certs + broken kubeconfig)
COPY setup_pki.sh /tmp/setup_pki.sh
RUN chmod +x /tmp/setup_pki.sh && /tmp/setup_pki.sh && rm /tmp/setup_pki.sh

# Copy and run etcd data setup (generates pre-failure snapshot)
COPY setup_etcd.sh /tmp/setup_etcd.sh
RUN chmod +x /tmp/setup_etcd.sh && /tmp/setup_etcd.sh && rm /tmp/setup_etcd.sh

WORKDIR /app
