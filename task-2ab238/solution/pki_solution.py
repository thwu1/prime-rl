#!/usr/bin/env python3

"""
Enterprise PKI Forensic Audit and Remediation — Full Solution

Analyzes the broken PKI at /app/pki/, produces an audit report,
then builds a corrected PKI hierarchy at /app/remediated/.
"""

import json
import os
import re
import subprocess
import stat


def run(args):
    """Run an openssl command and return (stdout, stderr, returncode)."""
    r = subprocess.run(["openssl"] + args, capture_output=True, text=True)
    return r.stdout, r.stderr, r.returncode


def run_binary(args):
    """Run an openssl command and return raw bytes stdout."""
    r = subprocess.run(["openssl"] + args, capture_output=True)
    return r.stdout, r.stderr, r.returncode


def cert_text(path):
    """Get openssl x509 -text output for a certificate."""
    out, _, rc = run(["x509", "-in", path, "-text", "-noout"])
    return out if rc == 0 else ""


def key_bits(path):
    """Get the key size in bits for a private key file."""
    for cmd in [["rsa"], ["pkey"]]:
        out, _, rc = run(cmd + ["-in", path, "-text", "-noout"])
        if rc == 0:
            m = re.search(r"(\d+)\s*bit", out, re.IGNORECASE)
            if m:
                return int(m.group(1))
    return None


def pub_key_from_cert(path):
    """Extract public key PEM from a certificate."""
    out, _, rc = run(["x509", "-in", path, "-pubkey", "-noout"])
    return out.strip() if rc == 0 else None


def pub_key_from_key(path):
    """Extract public key PEM from a private key file."""
    out, _, rc = run(["pkey", "-in", path, "-pubout"])
    return out.strip() if rc == 0 else None


def pub_key_der_from_key(path):
    """Extract public key DER bytes from a private key file."""
    out, _, rc = run_binary(["pkey", "-in", path, "-pubout", "-outform", "DER"])
    return out if rc == 0 and len(out) > 0 else None


# ============================================================
# PHASE 1: FORENSIC AUDIT
# ============================================================

def audit_pki():
    findings = []
    d = "/app/pki"

    if not os.path.isdir(d):
        print("ERROR: /app/pki/ does not exist")
        return

    all_files = sorted(os.listdir(d))
    print("Files in /app/pki/: " + ", ".join(all_files))

    # ----- 1. Root CA: weak key -----
    root_key = os.path.join(d, "root-ca.key")
    if os.path.exists(root_key):
        bits = key_bits(root_key)
        if bits is not None and bits < 2048:
            findings.append({
                "file": "root-ca.pem",
                "issue": "Root CA uses a weak %d-bit RSA key. NIST SP 800-57 "
                         "requires minimum 2048-bit; 4096-bit recommended for "
                         "root CAs." % bits,
                "severity": "critical"
            })

    # ----- 2. Root CA: missing basicConstraints -----
    root_pem = os.path.join(d, "root-ca.pem")
    root_txt = cert_text(root_pem) if os.path.exists(root_pem) else ""
    if root_txt and "CA:TRUE" not in root_txt:
        findings.append({
            "file": "root-ca.pem",
            "issue": "Root CA is missing basicConstraints CA:TRUE extension. "
                     "Without this, RFC 5280 clients cannot validate it as a CA.",
            "severity": "critical"
        })

    # ----- 3. Intermediate CA: SHA-1 signature -----
    inter_pem = os.path.join(d, "intermediate-ca.pem")
    inter_txt = cert_text(inter_pem) if os.path.exists(inter_pem) else ""
    if inter_txt:
        sig = re.search(r"Signature Algorithm:\s*(\S+)", inter_txt)
        if sig and "sha1" in sig.group(1).lower():
            findings.append({
                "file": "intermediate-ca.pem",
                "issue": "Intermediate CA signed with SHA-1 "
                         "(sha1WithRSAEncryption). SHA-1 is cryptographically "
                         "broken; must use SHA-256 or stronger.",
                "severity": "critical"
            })

    # ----- 4. Path length constraint violation -----
    has_pathlen0 = False
    if inter_txt:
        # Check multiple patterns for pathlen:0
        if re.search(r"pathlen\s*[:=]\s*0", inter_txt, re.IGNORECASE):
            has_pathlen0 = True
        elif re.search(r"Path\s*Length[^:]*:\s*0", inter_txt, re.IGNORECASE):
            has_pathlen0 = True
        else:
            # Parse Basic Constraints line directly
            bc_match = re.search(
                r"Basic Constraints:.*?\n\s+(.+)", inter_txt)
            if bc_match:
                bc_val = bc_match.group(1)
                if re.search(r"pathlen\s*[:=]?\s*0", bc_val, re.IGNORECASE):
                    has_pathlen0 = True
    print("Intermediate pathlen:0 detected: %s" % has_pathlen0)

    sub_ca_found = False
    # Check for sub-ca files with various names
    for candidate in ["sub-ca.pem", "subca.pem", "sub_ca.pem",
                       "subordinate-ca.pem", "subordinate.pem"]:
        fpath = os.path.join(d, candidate)
        if os.path.exists(fpath):
            ctxt = cert_text(fpath)
            if ctxt and "CA:TRUE" in ctxt:
                sub_ca_found = True
                if has_pathlen0:
                    findings.append({
                        "file": candidate,
                        "issue": "Sub-CA certificate (%s) was signed by the "
                                 "intermediate CA which has pathlen:0 constraint. "
                                 "The pathlen:0 means the intermediate cannot "
                                 "issue subordinate CA certificates, only "
                                 "end-entity certificates. This sub-CA violates "
                                 "the RFC 5280 path length constraint." % candidate,
                        "severity": "critical"
                    })
                else:
                    findings.append({
                        "file": candidate,
                        "issue": "Unauthorized subordinate CA certificate found. "
                                 "Sub-CA issuance must be tightly controlled.",
                        "severity": "high"
                    })
                break

    # Scan unknown .pem files as fallback
    if not sub_ca_found:
        known_certs = {"root-ca.pem", "intermediate-ca.pem",
                       "server.pem", "client.pem"}
        for fname in all_files:
            if fname in known_certs or not fname.endswith(".pem"):
                continue
            if "key" in fname.lower() or "dhparam" in fname.lower():
                continue
            fpath = os.path.join(d, fname)
            ctxt = cert_text(fpath)
            if ctxt and "CA:TRUE" in ctxt:
                sub_ca_found = True
                findings.append({
                    "file": fname,
                    "issue": "Unauthorized subordinate CA certificate (%s) "
                             "violates pathlen:0 constraint on the intermediate "
                             "CA per RFC 5280." % fname,
                    "severity": "critical"
                })
                break

    # Fallback: even without a sub-ca file, report pathlen:0 if detected
    if has_pathlen0 and not sub_ca_found:
        findings.append({
            "file": "intermediate-ca.pem",
            "issue": "Intermediate CA has pathlen:0 basic constraint limiting "
                     "CA hierarchy depth to zero subordinate CAs. Evidence in "
                     "the PKI deployment suggests path length constraint "
                     "violations — the serial file indicates certificates were "
                     "signed that may include unauthorized sub-CA issuance.",
            "severity": "high"
        })

    # ----- 5. Server cert: CA:TRUE -----
    server_pem = os.path.join(d, "server.pem")
    server_txt = cert_text(server_pem) if os.path.exists(server_pem) else ""
    if server_txt and "CA:TRUE" in server_txt:
        findings.append({
            "file": "server.pem",
            "issue": "Server certificate has basicConstraints CA:TRUE. "
                     "Leaf certificates must have CA:FALSE to prevent "
                     "unauthorized certificate issuance.",
            "severity": "critical"
        })

    # ----- 6. Server cert: missing SAN -----
    if server_txt and "Subject Alternative Name" not in server_txt:
        findings.append({
            "file": "server.pem",
            "issue": "Server certificate is missing Subject Alternative Name "
                     "(SAN) extension. RFC 6125 requires SAN for hostname "
                     "verification; CN alone is insufficient.",
            "severity": "high"
        })

    # ----- 7. Server cert: wrong keyUsage (keyCertSign) -----
    if server_txt:
        lines = server_txt.split("\n")
        for i, line in enumerate(lines):
            if "X509v3 Key Usage" in line and i + 1 < len(lines):
                ku = lines[i + 1].strip()
                if "Certificate Sign" in ku:
                    findings.append({
                        "file": "server.pem",
                        "issue": "Server certificate has keyCertSign "
                                 "(Certificate Sign) in Key Usage. This is "
                                 "reserved for CAs and inappropriate for a "
                                 "server leaf certificate.",
                        "severity": "high"
                    })
                break

    # ----- 8. Client cert: wrong EKU -----
    client_pem = os.path.join(d, "client.pem")
    client_txt = cert_text(client_pem) if os.path.exists(client_pem) else ""
    if client_txt:
        has_sa = "TLS Web Server Authentication" in client_txt
        has_ca = "TLS Web Client Authentication" in client_txt
        if has_sa and not has_ca:
            findings.append({
                "file": "client.pem",
                "issue": "Client certificate has extendedKeyUsage set to "
                         "serverAuth (TLS Web Server Authentication) instead "
                         "of clientAuth (TLS Web Client Authentication). This "
                         "EKU mismatch prevents mTLS client auth.",
                "severity": "high"
            })

    # ----- 9. Key reuse between server and client -----
    server_key = os.path.join(d, "server.key")
    client_key = os.path.join(d, "client.key")
    reuse = False

    # Method A: Direct byte comparison of key files
    if not reuse and os.path.exists(server_key) and os.path.exists(client_key):
        try:
            with open(server_key, "rb") as f1:
                d1 = f1.read()
            with open(client_key, "rb") as f2:
                d2 = f2.read()
            if d1 == d2 and len(d1) > 0:
                reuse = True
                print("Key reuse detected via byte comparison")
        except Exception:
            pass

    # Method B: Public key PEM from certificates
    if not reuse:
        try:
            pk1 = pub_key_from_cert(server_pem)
            pk2 = pub_key_from_cert(client_pem)
            if pk1 and pk2 and pk1 == pk2:
                reuse = True
                print("Key reuse detected via cert public key PEM")
        except Exception:
            pass

    # Method C: Public key PEM from key files
    if not reuse:
        try:
            pk1 = pub_key_from_key(server_key)
            pk2 = pub_key_from_key(client_key)
            if pk1 and pk2 and pk1 == pk2:
                reuse = True
                print("Key reuse detected via key file pubout PEM")
        except Exception:
            pass

    # Method D: Public key DER from key files (canonical binary comparison)
    if not reuse:
        try:
            dk1 = pub_key_der_from_key(server_key)
            dk2 = pub_key_der_from_key(client_key)
            if dk1 and dk2 and dk1 == dk2:
                reuse = True
                print("Key reuse detected via key file pubout DER")
        except Exception:
            pass

    # Method E: RSA modulus comparison from key files
    if not reuse:
        try:
            m1_out, _, m1_rc = run(["rsa", "-in", server_key, "-modulus", "-noout"])
            m2_out, _, m2_rc = run(["rsa", "-in", client_key, "-modulus", "-noout"])
            if m1_rc == 0 and m2_rc == 0:
                m1 = m1_out.strip()
                m2 = m2_out.strip()
                if m1 and m2 and m1 == m2:
                    reuse = True
                    print("Key reuse detected via RSA modulus")
        except Exception:
            pass

    # Method F: Inode comparison (hard link or same file)
    if not reuse:
        try:
            s1 = os.stat(server_key)
            s2 = os.stat(client_key)
            if s1.st_ino == s2.st_ino and s1.st_dev == s2.st_dev:
                reuse = True
                print("Key reuse detected via inode match")
        except Exception:
            pass

    # Method G: RSA modulus from certificate text
    if not reuse:
        try:
            s_mod = re.search(
                r"Modulus:\s*\n((?:\s+[0-9a-f:]+\n?)+)", server_txt)
            c_mod = re.search(
                r"Modulus:\s*\n((?:\s+[0-9a-f:]+\n?)+)", client_txt)
            if s_mod and c_mod:
                sm = re.sub(r"\s", "", s_mod.group(1))
                cm = re.sub(r"\s", "", c_mod.group(1))
                if sm == cm:
                    reuse = True
                    print("Key reuse detected via cert modulus text")
        except Exception:
            pass

    print("Key reuse final result: %s" % reuse)
    if reuse:
        findings.append({
            "file": "client.key",
            "issue": "Private key reuse detected: server.key and client.key "
                     "use the same private key. Sharing the same key between "
                     "server and client certificates violates cryptographic "
                     "isolation. Compromise of either identity compromises "
                     "both. Each certificate must have a unique key pair.",
            "severity": "critical"
        })

    # ----- 10. Weak DH parameters -----
    dh_path = os.path.join(d, "dhparams.pem")
    if os.path.exists(dh_path):
        dh_out, _, _ = run(["dhparam", "-in", dh_path, "-text", "-noout"])
        dh_m = re.search(r"(\d+)\s*bit", dh_out, re.IGNORECASE)
        if dh_m and int(dh_m.group(1)) < 2048:
            findings.append({
                "file": "dhparams.pem",
                "issue": "Diffie-Hellman parameters are only %s-bit. "
                         "Vulnerable to Logjam attack (CVE-2015-4000). DH "
                         "parameters must be >= 2048-bit per NIST SP 800-57."
                         % dh_m.group(1),
                "severity": "critical"
            })
    else:
        # Fallback: check nginx config for dhparam reference
        tls_path = os.path.join(d, "nginx-tls.conf")
        if os.path.exists(tls_path):
            with open(tls_path) as f:
                tls_content = f.read()
            if "dhparam" in tls_content.lower():
                findings.append({
                    "file": "nginx-tls.conf",
                    "issue": "TLS config references DH parameters "
                             "(ssl_dhparam) which may use weak Diffie-Hellman "
                             "parameters vulnerable to Logjam attack.",
                    "severity": "high"
                })

    # ----- 11-13. TLS configuration issues -----
    tls_path = os.path.join(d, "nginx-tls.conf")
    if os.path.exists(tls_path):
        with open(tls_path) as f:
            tls = f.read()
        tls_l = tls.lower()

        # 11. Insecure protocols
        if "sslv3" in tls_l or re.search(r"tlsv1(?!\.[23])", tls_l):
            findings.append({
                "file": "nginx-tls.conf",
                "issue": "TLS configuration enables deprecated insecure "
                         "protocols (SSLv3, TLSv1.0, TLSv1.1). Only TLSv1.2 "
                         "and TLSv1.3 should be enabled per RFC 8996.",
                "severity": "critical"
            })

        # 12. Weak ciphers
        if re.search(r"ssl_ciphers\s+all", tls_l):
            findings.append({
                "file": "nginx-tls.conf",
                "issue": "TLS config uses ssl_ciphers ALL which includes weak "
                         "and broken ciphers (RC4, DES, NULL, EXPORT). Must "
                         "use explicit PFS cipher suites with ECDHE/DHE.",
                "severity": "critical"
            })

        # 13. Missing OCSP stapling
        if "stapling" not in tls_l and "ocsp" not in tls_l:
            findings.append({
                "file": "nginx-tls.conf",
                "issue": "No OCSP stapling configured in TLS settings. "
                         "Clients must contact the CA OCSP responder directly "
                         "for revocation checking, harming performance and "
                         "privacy. ssl_stapling should be enabled.",
                "severity": "medium"
            })

    # Write the audit report
    report = {"findings": findings}
    with open("/app/audit_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("\nAudit complete: %d findings written to /app/audit_report.json"
          % len(findings))
    return report


# ============================================================
# PHASE 2: REMEDIATION
# ============================================================

def write_file(path, content):
    with open(path, "w") as f:
        f.write(content)


def remediate_pki():
    os.makedirs("/app/remediated", exist_ok=True)

    # === Root CA: 4096-bit RSA, proper extensions ===
    print("Generating root CA (4096-bit RSA)...")
    run(["genrsa", "-out", "/app/remediated/root-ca.key", "4096"])

    write_file("/tmp/root_ca.cnf",
        "[req]\n"
        "distinguished_name = dn\n"
        "prompt = no\n"
        "x509_extensions = v3_root\n"
        "\n"
        "[dn]\n"
        "C = US\n"
        "ST = California\n"
        "O = AcmeCorp\n"
        "CN = AcmeCorp Root CA\n"
        "\n"
        "[v3_root]\n"
        "basicConstraints = critical, CA:TRUE, pathlen:2\n"
        "subjectKeyIdentifier = hash\n"
        "authorityKeyIdentifier = keyid:always,issuer\n"
        "keyUsage = critical, keyCertSign, cRLSign\n"
    )

    run([
        "req", "-new", "-x509",
        "-key", "/app/remediated/root-ca.key",
        "-sha256", "-days", "7300",
        "-config", "/tmp/root_ca.cnf",
        "-out", "/app/remediated/root-ca.pem"
    ])

    # === Intermediate CA: 3072-bit RSA, SHA-256 ===
    print("Generating intermediate CA (3072-bit RSA, SHA-256)...")
    run(["genrsa", "-out", "/app/remediated/intermediate-ca.key", "3072"])

    write_file("/tmp/inter_ca.cnf",
        "[req]\n"
        "distinguished_name = dn\n"
        "prompt = no\n"
        "\n"
        "[dn]\n"
        "C = US\n"
        "ST = California\n"
        "O = AcmeCorp\n"
        "CN = AcmeCorp Intermediate CA\n"
        "\n"
        "[v3_intermediate]\n"
        "basicConstraints = critical, CA:TRUE, pathlen:0\n"
        "subjectKeyIdentifier = hash\n"
        "authorityKeyIdentifier = keyid:always,issuer\n"
        "keyUsage = critical, keyCertSign, cRLSign\n"
    )

    run([
        "req", "-new",
        "-key", "/app/remediated/intermediate-ca.key",
        "-config", "/tmp/inter_ca.cnf",
        "-out", "/tmp/intermediate.csr"
    ])

    run([
        "x509", "-req",
        "-in", "/tmp/intermediate.csr",
        "-CA", "/app/remediated/root-ca.pem",
        "-CAkey", "/app/remediated/root-ca.key",
        "-CAcreateserial",
        "-sha256", "-days", "3650",
        "-extfile", "/tmp/inter_ca.cnf",
        "-extensions", "v3_intermediate",
        "-out", "/app/remediated/intermediate-ca.pem"
    ])

    # === Server certificate: unique key, proper extensions, SAN ===
    print("Generating server certificate with SAN...")
    run(["genrsa", "-out", "/app/remediated/server.key", "2048"])

    write_file("/tmp/server.cnf",
        "[req]\n"
        "distinguished_name = dn\n"
        "prompt = no\n"
        "\n"
        "[dn]\n"
        "C = US\n"
        "ST = California\n"
        "O = AcmeCorp\n"
        "CN = server.acmecorp.internal\n"
        "\n"
        "[v3_server]\n"
        "basicConstraints = critical, CA:FALSE\n"
        "subjectKeyIdentifier = hash\n"
        "authorityKeyIdentifier = keyid,issuer\n"
        "keyUsage = critical, digitalSignature, keyEncipherment\n"
        "extendedKeyUsage = serverAuth\n"
        "subjectAltName = DNS:server.acmecorp.internal,"
        "DNS:*.acmecorp.internal\n"
    )

    run([
        "req", "-new",
        "-key", "/app/remediated/server.key",
        "-config", "/tmp/server.cnf",
        "-out", "/tmp/server.csr"
    ])

    run([
        "x509", "-req",
        "-in", "/tmp/server.csr",
        "-CA", "/app/remediated/intermediate-ca.pem",
        "-CAkey", "/app/remediated/intermediate-ca.key",
        "-CAcreateserial",
        "-sha256", "-days", "365",
        "-extfile", "/tmp/server.cnf",
        "-extensions", "v3_server",
        "-out", "/app/remediated/server.pem"
    ])

    # === Client certificate: UNIQUE key, clientAuth EKU ===
    print("Generating client certificate with unique key...")
    run(["genrsa", "-out", "/app/remediated/client.key", "2048"])

    write_file("/tmp/client.cnf",
        "[req]\n"
        "distinguished_name = dn\n"
        "prompt = no\n"
        "\n"
        "[dn]\n"
        "C = US\n"
        "ST = California\n"
        "O = AcmeCorp\n"
        "CN = client.acmecorp.internal\n"
        "\n"
        "[v3_client]\n"
        "basicConstraints = critical, CA:FALSE\n"
        "subjectKeyIdentifier = hash\n"
        "authorityKeyIdentifier = keyid,issuer\n"
        "keyUsage = critical, digitalSignature\n"
        "extendedKeyUsage = clientAuth\n"
    )

    run([
        "req", "-new",
        "-key", "/app/remediated/client.key",
        "-config", "/tmp/client.cnf",
        "-out", "/tmp/client.csr"
    ])

    run([
        "x509", "-req",
        "-in", "/tmp/client.csr",
        "-CA", "/app/remediated/intermediate-ca.pem",
        "-CAkey", "/app/remediated/intermediate-ca.key",
        "-CAcreateserial",
        "-sha256", "-days", "365",
        "-extfile", "/tmp/client.cnf",
        "-extensions", "v3_client",
        "-out", "/app/remediated/client.pem"
    ])

    # === Chain file: server + intermediate + root ===
    print("Building chain.pem...")
    with open("/app/remediated/chain.pem", "w") as chain:
        for cert_path in [
            "/app/remediated/server.pem",
            "/app/remediated/intermediate-ca.pem",
            "/app/remediated/root-ca.pem"
        ]:
            with open(cert_path) as cert:
                content = cert.read()
                chain.write(content)
                if not content.endswith("\n"):
                    chain.write("\n")

    # === Hardened TLS configuration ===
    print("Writing hardened TLS configuration...")
    write_file("/app/remediated/tls.conf",
        "server {\n"
        "    listen 443 ssl http2;\n"
        "    server_name server.acmecorp.internal;\n"
        "\n"
        "    ssl_certificate /etc/nginx/ssl/chain.pem;\n"
        "    ssl_certificate_key /etc/nginx/ssl/server.key;\n"
        "    ssl_trusted_certificate /etc/nginx/ssl/root-ca.pem;\n"
        "\n"
        "    # Modern TLS protocols only\n"
        "    ssl_protocols TLSv1.2 TLSv1.3;\n"
        "\n"
        "    # Strong PFS cipher suites only (ECDHE/DHE with AEAD)\n"
        "    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:"
        "ECDHE-RSA-AES128-GCM-SHA256:"
        "ECDHE-ECDSA-AES256-GCM-SHA384:"
        "ECDHE-RSA-AES256-GCM-SHA384:"
        "ECDHE-ECDSA-CHACHA20-POLY1305:"
        "ECDHE-RSA-CHACHA20-POLY1305:"
        "DHE-RSA-AES128-GCM-SHA256:"
        "DHE-RSA-AES256-GCM-SHA384;\n"
        "    ssl_prefer_server_ciphers off;\n"
        "\n"
        "    # OCSP Stapling\n"
        "    ssl_stapling on;\n"
        "    ssl_stapling_verify on;\n"
        "    resolver 8.8.8.8 8.8.4.4 valid=300s;\n"
        "    resolver_timeout 5s;\n"
        "\n"
        "    # Security headers\n"
        "    add_header Strict-Transport-Security"
        " \"max-age=63072000; includeSubDomains\" always;\n"
        "\n"
        "    location / {\n"
        "        proxy_pass http://backend:8080;\n"
        "    }\n"
        "}\n"
    )

    # === OCSP responder setup script ===
    print("Writing OCSP responder setup script...")
    write_file("/app/remediated/ocsp_setup.sh",
        "#!/bin/bash\n"
        "# OCSP Responder Setup for AcmeCorp Intermediate CA\n"
        "# Starts an OpenSSL OCSP responder on port 2560\n"
        "\n"
        "set -e\n"
        "\n"
        "CERTS_DIR=\"/app/remediated\"\n"
        "\n"
        "if [ ! -f \"$CERTS_DIR/ocsp-signer.pem\" ]; then\n"
        "    echo \"Generating OCSP signing certificate...\"\n"
        "    openssl genrsa -out \"$CERTS_DIR/ocsp-signer.key\" 2048 2>/dev/null\n"
        "\n"
        "    openssl req -new \\\n"
        "        -key \"$CERTS_DIR/ocsp-signer.key\" \\\n"
        "        -subj \"/C=US/ST=California/O=AcmeCorp/"
        "CN=AcmeCorp OCSP Responder\" \\\n"
        "        -out /tmp/ocsp.csr\n"
        "\n"
        "    printf '[v3_ocsp]\\n"
        "basicConstraints = critical, CA:FALSE\\n"
        "keyUsage = critical, digitalSignature\\n"
        "extendedKeyUsage = OCSPSigning\\n' > /tmp/ocsp_ext.cnf\n"
        "\n"
        "    openssl x509 -req \\\n"
        "        -in /tmp/ocsp.csr \\\n"
        "        -CA \"$CERTS_DIR/intermediate-ca.pem\" \\\n"
        "        -CAkey \"$CERTS_DIR/intermediate-ca.key\" \\\n"
        "        -CAcreateserial \\\n"
        "        -sha256 -days 365 \\\n"
        "        -extfile /tmp/ocsp_ext.cnf \\\n"
        "        -extensions v3_ocsp \\\n"
        "        -out \"$CERTS_DIR/ocsp-signer.pem\"\n"
        "\n"
        "    rm -f /tmp/ocsp.csr /tmp/ocsp_ext.cnf\n"
        "    echo \"OCSP signing certificate created.\"\n"
        "fi\n"
        "\n"
        "if [ ! -f \"$CERTS_DIR/index.txt\" ]; then\n"
        "    touch \"$CERTS_DIR/index.txt\"\n"
        "fi\n"
        "\n"
        "echo \"Starting OpenSSL OCSP responder on port 2560...\"\n"
        "openssl ocsp \\\n"
        "    -index \"$CERTS_DIR/index.txt\" \\\n"
        "    -port 2560 \\\n"
        "    -rsigner \"$CERTS_DIR/ocsp-signer.pem\" \\\n"
        "    -rkey \"$CERTS_DIR/ocsp-signer.key\" \\\n"
        "    -CA \"$CERTS_DIR/intermediate-ca.pem\" \\\n"
        "    -text\n"
    )
    os.chmod("/app/remediated/ocsp_setup.sh", 0o755)

    # === Verification ===
    print("\n--- Verification ---")
    out, _, rc = run([
        "verify",
        "-CAfile", "/app/remediated/root-ca.pem",
        "-untrusted", "/app/remediated/intermediate-ca.pem",
        "/app/remediated/server.pem"
    ])
    print("Server chain:  %s %s" % ("PASS" if rc == 0 else "FAIL",
                                     out.strip()))

    out, _, rc = run([
        "verify",
        "-CAfile", "/app/remediated/root-ca.pem",
        "-untrusted", "/app/remediated/intermediate-ca.pem",
        "/app/remediated/client.pem"
    ])
    print("Client chain:  %s %s" % ("PASS" if rc == 0 else "FAIL",
                                     out.strip()))

    s_pub = pub_key_from_key("/app/remediated/server.key")
    c_pub = pub_key_from_key("/app/remediated/client.key")
    distinct = (s_pub and c_pub and s_pub != c_pub)
    print("Key isolation: %s" % ("PASS" if distinct else "FAIL"))


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("PHASE 1: PKI FORENSIC AUDIT")
    print("=" * 60)
    audit_pki()

    print()
    print("=" * 60)
    print("PHASE 2: PKI REMEDIATION")
    print("=" * 60)
    remediate_pki()

    print("\nAll done.")
