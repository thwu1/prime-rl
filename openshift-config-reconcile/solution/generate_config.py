#!/usr/bin/env python3

"""
Generate a complete, correct OpenShift multi-tenant cluster configuration
from the specification at /app/spec.yaml. Produces all resources in
/app/output/ and fixes all errors present in /app/broken/.
"""

import os
import subprocess
import yaml

SPEC_PATH = "/app/spec.yaml"
OUTPUT = "/app/output"


def main():
    with open(SPEC_PATH) as f:
        spec = yaml.safe_load(f)

    for d in [
        "rbac", "network-policies", "quotas",
        "limit-ranges", "tls", "routes", "scc",
    ]:
        os.makedirs(os.path.join(OUTPUT, d), exist_ok=True)

    generate_htpasswd(spec)
    generate_oauth(spec)
    generate_namespaces(spec)
    generate_rbac(spec)
    generate_network_policies(spec)
    generate_quotas(spec)
    generate_limit_ranges(spec)
    generate_tls(spec)
    generate_routes(spec)
    generate_scc(spec)
    generate_kustomization()


# ── helpers ──────────────────────────────────────────────────────


def write_yaml(path, doc):
    with open(path, "w") as f:
        yaml.dump(doc, f, default_flow_style=False, sort_keys=False)


def write_yaml_all(path, docs):
    with open(path, "w") as f:
        yaml.dump_all(docs, f, default_flow_style=False, sort_keys=False)


# ── htpasswd (bcrypt) ────────────────────────────────────────────


def generate_htpasswd(spec):
    htpasswd_path = os.path.join(OUTPUT, "htpasswd")
    users = spec["identity_provider"]["users"]
    # First user: create file (-c)
    subprocess.run(
        ["htpasswd", "-c", "-B", "-b", htpasswd_path,
         users[0]["username"], users[0]["password"]],
        check=True, capture_output=True,
    )
    for user in users[1:]:
        subprocess.run(
            ["htpasswd", "-B", "-b", htpasswd_path,
             user["username"], user["password"]],
            check=True, capture_output=True,
        )


# ── OAuth CR ─────────────────────────────────────────────────────


def generate_oauth(spec):
    idp = spec["identity_provider"]
    doc = {
        "apiVersion": "config.openshift.io/v1",
        "kind": "OAuth",
        "metadata": {"name": "cluster"},
        "spec": {
            "identityProviders": [
                {
                    "name": idp["name"],
                    "mappingMethod": idp["mapping_method"],
                    "type": idp["type"],
                    "htpasswd": {
                        "fileData": {"name": idp["secret_name"]},
                    },
                }
            ]
        },
    }
    write_yaml(os.path.join(OUTPUT, "oauth.yaml"), doc)


# ── Namespaces ───────────────────────────────────────────────────


def generate_namespaces(spec):
    docs = []
    for ns in spec["namespaces"]:
        docs.append({
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": ns["name"],
                "labels": dict(ns["labels"]),
            },
        })
    write_yaml_all(os.path.join(OUTPUT, "namespaces.yaml"), docs)


# ── RBAC ─────────────────────────────────────────────────────────


def generate_rbac(spec):
    # ClusterRoleBindings
    for crb in spec["rbac"]["cluster_role_bindings"]:
        doc = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRoleBinding",
            "metadata": {"name": crb["name"]},
            "roleRef": {
                "apiGroup": "rbac.authorization.k8s.io",
                "kind": "ClusterRole",
                "name": crb["cluster_role"],
            },
            "subjects": [
                {
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "User",
                    "name": crb["user"],
                }
            ],
        }
        write_yaml(os.path.join(OUTPUT, "rbac", f"{crb['name']}.yaml"), doc)

    # RoleBindings
    for rb in spec["rbac"]["role_bindings"]:
        subject = {}
        if "group" in rb:
            subject = {
                "apiGroup": "rbac.authorization.k8s.io",
                "kind": "Group",
                "name": rb["group"],
            }
        elif "user" in rb:
            subject = {
                "apiGroup": "rbac.authorization.k8s.io",
                "kind": "User",
                "name": rb["user"],
            }

        doc = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "RoleBinding",
            "metadata": {
                "name": rb["name"],
                "namespace": rb["namespace"],
            },
            "roleRef": {
                "apiGroup": "rbac.authorization.k8s.io",
                "kind": "ClusterRole",
                "name": rb["role"],
            },
            "subjects": [subject],
        }
        write_yaml(os.path.join(OUTPUT, "rbac", f"{rb['name']}.yaml"), doc)


# ── NetworkPolicies ──────────────────────────────────────────────


def generate_network_policies(spec):
    for ns_name, policies in spec["network_policies"].items():
        docs = []
        for pol in policies:
            doc = {
                "apiVersion": "networking.k8s.io/v1",
                "kind": "NetworkPolicy",
                "metadata": {
                    "name": pol["name"],
                    "namespace": ns_name,
                },
                "spec": {
                    "podSelector": pol["pod_selector"],
                    "policyTypes": pol["policy_types"],
                },
            }
            if "ingress" in pol:
                doc["spec"]["ingress"] = pol["ingress"]
            if "egress" in pol:
                doc["spec"]["egress"] = pol["egress"]
            docs.append(doc)
        write_yaml_all(
            os.path.join(OUTPUT, "network-policies", f"{ns_name}.yaml"),
            docs,
        )


# ── ResourceQuotas ───────────────────────────────────────────────


def generate_quotas(spec):
    for q in spec["quotas"]:
        doc = {
            "apiVersion": "v1",
            "kind": "ResourceQuota",
            "metadata": {
                "name": q["name"],
                "namespace": q["namespace"],
            },
            "spec": {"hard": dict(q["hard"])},
        }
        write_yaml(
            os.path.join(OUTPUT, "quotas", f"{q['namespace']}.yaml"), doc
        )


# ── LimitRanges ──────────────────────────────────────────────────


def generate_limit_ranges(spec):
    for lr in spec["limit_ranges"]:
        doc = {
            "apiVersion": "v1",
            "kind": "LimitRange",
            "metadata": {
                "name": lr["name"],
                "namespace": lr["namespace"],
            },
            "spec": {"limits": lr["limits"]},
        }
        write_yaml(
            os.path.join(OUTPUT, "limit-ranges", f"{lr['namespace']}.yaml"),
            doc,
        )


# ── TLS Certificates ────────────────────────────────────────────


def generate_tls(spec):
    tls_dir = os.path.join(OUTPUT, "tls")

    # Generate CA
    subprocess.run(
        ["openssl", "genrsa", "-out", os.path.join(tls_dir, "ca.key"), "2048"],
        capture_output=True, check=True,
    )
    subprocess.run(
        [
            "openssl", "req", "-x509", "-new", "-nodes",
            "-key", os.path.join(tls_dir, "ca.key"),
            "-sha256", "-days", "3650",
            "-out", os.path.join(tls_dir, "ca.crt"),
            "-subj", "/CN=ACME Internal CA",
        ],
        capture_output=True, check=True,
    )

    # Generate frontend cert with correct SANs
    edge_route = spec["tls"]["routes"][0]
    san_list = ",".join(f"DNS:{s}" for s in edge_route["san"])

    san_config = (
        "[req]\n"
        "req_extensions = v3_req\n"
        "distinguished_name = req_distinguished_name\n"
        "[req_distinguished_name]\n"
        "[v3_req]\n"
        f"subjectAltName = {san_list}\n"
    )
    with open("/tmp/san.cnf", "w") as f:
        f.write(san_config)

    subprocess.run(
        [
            "openssl", "genrsa",
            "-out", os.path.join(tls_dir, "frontend.key"), "2048",
        ],
        capture_output=True, check=True,
    )
    subprocess.run(
        [
            "openssl", "req", "-new",
            "-key", os.path.join(tls_dir, "frontend.key"),
            "-out", "/tmp/frontend.csr",
            "-subj", f"/CN={edge_route['hostname']}",
            "-config", "/tmp/san.cnf",
        ],
        capture_output=True, check=True,
    )

    with open("/tmp/san_ext.cnf", "w") as f:
        f.write(f"subjectAltName = {san_list}\n")

    subprocess.run(
        [
            "openssl", "x509", "-req",
            "-in", "/tmp/frontend.csr",
            "-CA", os.path.join(tls_dir, "ca.crt"),
            "-CAkey", os.path.join(tls_dir, "ca.key"),
            "-CAcreateserial",
            "-out", os.path.join(tls_dir, "frontend.crt"),
            "-days", "365", "-sha256",
            "-extfile", "/tmp/san_ext.cnf",
        ],
        capture_output=True, check=True,
    )

    for tmp in ["/tmp/frontend.csr", "/tmp/san.cnf", "/tmp/san_ext.cnf"]:
        if os.path.exists(tmp):
            os.remove(tmp)
    srl = os.path.join(tls_dir, "ca.srl")
    if os.path.exists(srl):
        os.remove(srl)


# ── Routes ───────────────────────────────────────────────────────


def generate_routes(spec):
    tls_dir = os.path.join(OUTPUT, "tls")

    for route_spec in spec["tls"]["routes"]:
        doc = {
            "apiVersion": "route.openshift.io/v1",
            "kind": "Route",
            "metadata": {
                "name": route_spec["name"],
                "namespace": route_spec["namespace"],
            },
            "spec": {
                "host": route_spec["hostname"],
                "to": {
                    "kind": "Service",
                    "name": route_spec["service"],
                },
                "port": {"targetPort": route_spec["target_port"]},
                "tls": {"termination": route_spec["type"]},
            },
        }

        if route_spec["type"] == "edge":
            with open(os.path.join(tls_dir, "frontend.crt")) as f:
                cert = f.read()
            with open(os.path.join(tls_dir, "frontend.key")) as f:
                key = f.read()
            with open(os.path.join(tls_dir, "ca.crt")) as f:
                ca_cert = f.read()
            doc["spec"]["tls"]["certificate"] = cert
            doc["spec"]["tls"]["key"] = key
            doc["spec"]["tls"]["caCertificate"] = ca_cert

        write_yaml(
            os.path.join(OUTPUT, "routes", f"{route_spec['name']}.yaml"), doc
        )


# ── SCC ──────────────────────────────────────────────────────────


def generate_scc(spec):
    for scc_spec in spec["scc"]:
        sa_doc = {
            "apiVersion": "v1",
            "kind": "ServiceAccount",
            "metadata": {
                "name": scc_spec["service_account"],
                "namespace": scc_spec["namespace"],
            },
        }
        crb_doc = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRoleBinding",
            "metadata": {
                "name": (
                    f"{scc_spec['service_account']}-{scc_spec['scc']}"
                ),
            },
            "roleRef": {
                "apiGroup": "rbac.authorization.k8s.io",
                "kind": "ClusterRole",
                "name": f"system:openshift:scc:{scc_spec['scc']}",
            },
            "subjects": [
                {
                    "kind": "ServiceAccount",
                    "name": scc_spec["service_account"],
                    "namespace": scc_spec["namespace"],
                }
            ],
        }
        write_yaml_all(
            os.path.join(
                OUTPUT, "scc", f"{scc_spec['service_account']}.yaml"
            ),
            [sa_doc, crb_doc],
        )


# ── Kustomization ────────────────────────────────────────────────


def generate_kustomization():
    resources = ["namespaces.yaml", "oauth.yaml"]

    for subdir in [
        "rbac", "network-policies", "quotas",
        "limit-ranges", "routes", "scc",
    ]:
        d = os.path.join(OUTPUT, subdir)
        if os.path.isdir(d):
            for fname in sorted(os.listdir(d)):
                if fname.endswith((".yaml", ".yml")):
                    resources.append(f"{subdir}/{fname}")

    doc = {
        "apiVersion": "kustomize.config.k8s.io/v1beta1",
        "kind": "Kustomization",
        "resources": resources,
    }
    write_yaml(os.path.join(OUTPUT, "kustomization.yaml"), doc)


if __name__ == "__main__":
    main()
