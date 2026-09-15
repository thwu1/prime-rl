"""
Encryption engines used by the vault daemon.

The vault has used three engine versions over its lifecycle:
    v1  AES-128-ECB   (engines/ecb_v1.py)
    v2  AES-256-CTR   (engines/ctr_v2.py)
    v3  AES-256-GCM   (engines/gcm_v3.py)

See the deployment manifest at /app/config/deployment_manifest.json
for activation timelines.
"""
