#!/usr/bin/env python3
"""Generate encrypted exfiltration evidence for the forensic challenge.
This runs during Docker build in a multi-stage builder to avoid leaking plaintext."""
import hashlib
import os
import struct
import tarfile
import io

SEED = "pr0j3ct_m4yh3m_2024"

SENSITIVE_FILES = {
    "customer_db.csv": """id,name,email,phone,ssn,credit_card,address
1,John Smith,jsmith@acmecorp.com,555-0101,123-45-6789,4111111111111111,"123 Oak St, Portland OR 97201"
2,Jane Doe,jdoe@acmecorp.com,555-0102,987-65-4321,5500000000000004,"456 Elm Ave, Seattle WA 98101"
3,Robert Wilson,rwilson@acmecorp.com,555-0103,456-78-9012,340000000000009,"789 Pine Rd, Denver CO 80201"
4,Sarah Chen,schen@acmecorp.com,555-0104,234-56-7890,6011111111111117,"321 Maple Dr, Austin TX 78701"
5,Michael Brown,mbrown@acmecorp.com,555-0105,345-67-8901,3530111333300000,"654 Cedar Ln, Chicago IL 60601"
6,Emily Davis,edavis@acmecorp.com,555-0106,567-89-0123,4222222222222,"987 Birch Way, Boston MA 02101"
7,David Martinez,dmartinez@acmecorp.com,555-0107,678-90-1234,5105105105105100,"147 Spruce Ct, Miami FL 33101"
8,Lisa Anderson,landerson@acmecorp.com,555-0108,789-01-2345,4000056655665556,"258 Willow Pl, Atlanta GA 30301"
9,James Taylor,jtaylor@acmecorp.com,555-0109,890-12-3456,5200828282828210,"369 Aspen Blvd, Phoenix AZ 85001"
10,Maria Garcia,mgarcia@acmecorp.com,555-0110,901-23-4567,371449635398431,"480 Redwood Ave, San Diego CA 92101"
""",
    "api_credentials.txt": """# Production API Keys - CONFIDENTIAL
# Last rotated: 2024-02-15
# Owner: platform-team@acmecorp.com

AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
AWS_REGION=us-west-2

STRIPE_LIVE_SECRET=sk_live_4eC39HqLyjWDarjtT1zdp7dc
STRIPE_LIVE_PUBLISHABLE=pk_live_TYooMQauvdEDq54NiTphI7jx

GITHUB_PAT=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef12
DATADOG_API_KEY=a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4
SENDGRID_API_KEY=SG.xxxxxxxxxxxxxxxxxxxxx.yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy

DATABASE_URL=postgresql://prod_admin:Pr0d_S3cur3_P@ss!@db-primary.internal.acmecorp.com:5432/production
REDIS_URL=redis://:R3d1s_Auth_T0k3n@cache.internal.acmecorp.com:6379/0
""",
    "ssh_private_keys.txt": """# SSH Private Keys - Collected from /home/*/.ssh/
# Timestamp: 2024-03-15T15:01:22Z

### User: admin (10.0.4.5) ###
-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACA7Jf5BQLetUGSfamNJTB5wy7BX3XNh4rVKRljcFzZPOwAAAJjXEPHD1xDx
wwAAAAtzc2gtZWQyNTUxOQAAACA7Jf5BQLexUGSfamNJTB5wy7BX3XNh4rVKRljcFzZPOw
AAAEBfE6stVCiMGhTv0xHWJbe2rqP3N5UHq4WwTMGPVNmBQDsl/kFAt7FQZJ9qY0lMHnDL
sFfdc2HitUpGWNwXNk87AAAAEWFkbWluQHByb2Qtd2ViLTAx
-----END OPENSSH PRIVATE KEY-----

### User: deploy (10.0.4.10) ###
-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACBKvfR0MXV9gxEi7aKu6bc/tnPCST+2gL7GTkiVCPQajAAAAJhoVkd9aFZH
fQAAAAtzc2gtZWQyNTUxOQAAACBKvfR0MXV9gxEi7aKu6bc/tnPCST+2gL7GTkiVCPQajA
AAAEAkf5CiIR4rF6G2pYbqn8NHXWQ7Y4fVCIuJr2QmaPlNEq99HQxdX2DESLtoq7ptz+2c
8JJP7aAvsZOSJUI9BqMAAAAEmRlcGxveUBwcm9kLXdlYi0wMQ==
-----END OPENSSH PRIVATE KEY-----
""",
    "internal_network_map.txt": """# AcmeCorp Internal Network Topology
# Generated: 2024-03-01
# Classification: CONFIDENTIAL - Internal Use Only

## Production Environment
10.0.1.0/24  - Production Web Servers (nginx reverse proxy)
  10.0.1.10  - web-prod-01 (primary)
  10.0.1.11  - web-prod-02 (secondary)
  10.0.1.12  - web-prod-03 (canary)

10.0.2.0/24  - Database Cluster
  10.0.2.10  - db-primary.internal.acmecorp.com (PostgreSQL 15, master)
  10.0.2.11  - db-replica-01 (read replica)
  10.0.2.12  - db-replica-02 (read replica)

10.0.3.0/24  - Internal Services
  10.0.3.10  - api-gateway.internal.acmecorp.com
  10.0.3.11  - auth-service.internal.acmecorp.com
  10.0.3.12  - queue.internal.acmecorp.com (RabbitMQ)
  10.0.3.13  - cache.internal.acmecorp.com (Redis 7.2)

10.0.4.0/24  - Management / Jump Hosts
  10.0.4.5   - jump-01.internal.acmecorp.com
  10.0.4.10  - deploy-srv.internal.acmecorp.com
  10.0.4.15  - monitoring.internal.acmecorp.com (Grafana/Prometheus)

## VPN Endpoints
vpn.acmecorp.com - Employee VPN (WireGuard)
  Subnet: 172.16.0.0/16

## Cloud Resources (AWS us-west-2)
  Account ID: 123456789012
  VPC: vpc-0abc123def456789
  EKS Cluster: acme-prod-cluster
"""
}


def kdf(seed, iterations=50000):
    dk = hashlib.sha512(seed.encode('utf-8')).digest()
    for _ in range(iterations):
        dk = hashlib.sha512(dk).digest()
    return dk[:32]


def crypt(data, key):
    result = bytearray()
    nonce = os.urandom(12)
    for i in range(0, len(data), 32):
        counter_block = nonce + struct.pack('>I', i // 32)
        keystream = hashlib.sha256(key + counter_block).digest()
        chunk = data[i:i + 32]
        result.extend(b ^ k for b, k in zip(chunk, keystream[:len(chunk)]))
    return nonce + bytes(result)


def main():
    # Create tar archive of sensitive files
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode='w:gz') as tar:
        for filename, content in sorted(SENSITIVE_FILES.items()):
            data = content.encode('utf-8')
            info = tarfile.TarInfo(name=filename)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

    # Encrypt with the attacker's seed
    key = kdf(SEED)
    encrypted = crypt(tar_buffer.getvalue(), key)

    with open('/tmp/encrypted_exfil.bin', 'wb') as f:
        f.write(encrypted)

    print(f"[+] Generated encrypted_exfil.bin ({len(encrypted)} bytes)")


if __name__ == '__main__':
    main()
