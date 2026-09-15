"""
Fix the broken static pod manifests.

"""

import yaml
import os
import copy

MANIFESTS_DIR = "/app/manifests"
FIXED_DIR = "/app/manifests-fixed"
os.makedirs(FIXED_DIR, exist_ok=True)


def load_manifest(name):
    with open(os.path.join(MANIFESTS_DIR, name)) as f:
        return yaml.safe_load(f)


def save_manifest(name, data):
    with open(os.path.join(FIXED_DIR, name), "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def get_command(manifest):
    return manifest["spec"]["containers"][0]["command"]


def set_flag(command, flag, value):
    """Set a flag in the command list. If it exists, replace it; otherwise append."""
    prefix = f"--{flag}="
    for i, item in enumerate(command):
        if item.startswith(prefix):
            command[i] = f"{prefix}{value}"
            return
    command.append(f"{prefix}{value}")


def remove_flag(command, flag):
    """Remove a flag from the command list."""
    prefix = f"--{flag}="
    command[:] = [item for item in command if not item.startswith(prefix)]


# ============================================================
# Fix kube-apiserver.yaml
# ============================================================
apiserver = load_manifest("kube-apiserver.yaml")
cmd = get_command(apiserver)

# Fix 1: etcd port 2380 -> 2379
set_flag(cmd, "etcd-servers", "https://127.0.0.1:2379")

# Fix 2: TLS cert path server.crt -> apiserver.crt
set_flag(cmd, "tls-cert-file", "/etc/kubernetes/pki/apiserver.crt")

# Fix 3: TLS key path server.key -> apiserver.key
set_flag(cmd, "tls-private-key-file", "/etc/kubernetes/pki/apiserver.key")

# Fix 4: Authorization mode AlwaysAllow -> Node,RBAC
set_flag(cmd, "authorization-mode", "Node,RBAC")

# Fix 5: Add missing --service-cluster-ip-range
set_flag(cmd, "service-cluster-ip-range", "10.96.0.0/12")

save_manifest("kube-apiserver.yaml", apiserver)
print("  Fixed kube-apiserver.yaml")


# ============================================================
# Fix kube-scheduler.yaml
# ============================================================
scheduler = load_manifest("kube-scheduler.yaml")
cmd = get_command(scheduler)

# Fix 1: kubeconfig extension .config -> .conf
set_flag(cmd, "kubeconfig", "/etc/kubernetes/scheduler.conf")

# Fix 2: Volume name mismatch - volumes has "kubeconf" but volumeMounts has "kubeconfig"
# Fix the volume name to match the volumeMount
volumes = scheduler["spec"]["volumes"]
for vol in volumes:
    if vol["name"] == "kubeconf":
        vol["name"] = "kubeconfig"

save_manifest("kube-scheduler.yaml", scheduler)
print("  Fixed kube-scheduler.yaml")


# ============================================================
# Fix kube-controller-manager.yaml
# ============================================================
cm = load_manifest("kube-controller-manager.yaml")
cmd = get_command(cm)

# Fix 1: Add missing --cluster-signing-cert-file
set_flag(cmd, "cluster-signing-cert-file", "/etc/kubernetes/pki/ca.crt")

# Fix 2: Add missing --cluster-signing-key-file
set_flag(cmd, "cluster-signing-key-file", "/etc/kubernetes/pki/ca.key")

# Fix 3: bind-address 0.0.0.0 -> 127.0.0.1
set_flag(cmd, "bind-address", "127.0.0.1")

save_manifest("kube-controller-manager.yaml", cm)
print("  Fixed kube-controller-manager.yaml")


# ============================================================
# Fix etcd.yaml
# ============================================================
etcd = load_manifest("etcd.yaml")
cmd = get_command(etcd)

# Fix 1: data-dir /var/lib/etcd-data -> /var/lib/etcd
set_flag(cmd, "data-dir", "/var/lib/etcd")

# Fix 2: listen-client-urls port swap - 2380 -> 2379
set_flag(cmd, "listen-client-urls", "https://127.0.0.1:2379,https://192.168.1.10:2379")

# Fix 3: listen-peer-urls port swap - 2379 -> 2380
set_flag(cmd, "listen-peer-urls", "https://192.168.1.10:2380")

save_manifest("etcd.yaml", etcd)
print("  Fixed etcd.yaml")
