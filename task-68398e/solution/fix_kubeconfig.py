"""
Fix the broken admin kubeconfig.

"""

import yaml
import base64

# Read the fixed certificates
with open("/app/pki/ca.crt", "rb") as f:
    ca_data = base64.b64encode(f.read()).decode()

with open("/app/pki-fixed/admin.crt", "rb") as f:
    admin_cert_data = base64.b64encode(f.read()).decode()

with open("/app/pki-fixed/admin.key", "rb") as f:
    admin_key_data = base64.b64encode(f.read()).decode()

# Build a correct kubeconfig
kubeconfig = {
    "apiVersion": "v1",
    "kind": "Config",
    "clusters": [
        {
            "cluster": {
                "certificate-authority-data": ca_data,
                "server": "https://192.168.1.10:6443",
            },
            "name": "kubernetes",
        }
    ],
    "contexts": [
        {
            "context": {
                "cluster": "kubernetes",
                "user": "kubernetes-admin",
            },
            "name": "kubernetes-admin@kubernetes",
        }
    ],
    "current-context": "kubernetes-admin@kubernetes",
    "preferences": {},
    "users": [
        {
            "name": "kubernetes-admin",
            "user": {
                "client-certificate-data": admin_cert_data,
                "client-key-data": admin_key_data,
            },
        }
    ],
}

with open("/app/kubeconfig/admin.kubeconfig", "w") as f:
    yaml.dump(kubeconfig, f, default_flow_style=False, sort_keys=False)

print("  Fixed admin.kubeconfig")
