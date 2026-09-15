INCIDENT RESPONSE - PKI INFRASTRUCTURE AUDIT
=============================================

CLASSIFICATION: CONFIDENTIAL

BACKGROUND:
On 2024-03-15, the Security Operations Center detected anomalous encrypted
traffic leaving the corporate network via a multi-hop relay through internal
servers. Network forensics captured the encrypted session data before the
connection was terminated.

Analysis indicates the threat actor compromised two internal servers to
establish a multi-layer encrypted relay for data exfiltration. The session
key was protected by nested encryption using certificates from servers in
the relay chain.

AVAILABLE EVIDENCE:
  certificates/                       TLS certificates for all internal servers
  incident/captured_session.json      Relay chain metadata and encryption parameters
  incident/encrypted_relay_key.bin    Outer-layer encrypted relay key (RSA-OAEP)
  incident/encrypted_session_key.bin  AES-GCM wrapped inner RSA blob
  incident/encrypted_payload.bin      Encrypted exfiltration payload (AES-256-GCM)

PRIOR AUDIT FINDINGS:
The certificate generation tool was developed in-house and used a custom
random number generator for RSA key generation. All eight server certificates
were generated in a single batch session. Quality assurance flagged two
distinct categories of entropy concern before the tool was decommissioned:

  1. The PRNG state was not properly reseeded between some key generation
     operations, potentially causing entropy overlap across multiple keys.

  2. At least one key generation used a PRNG state with severely collapsed
     internal entropy, potentially producing prime factors with anomalous
     proximity characteristics.

Neither issue was fully investigated before deployment. The number of
affected certificates is unknown. Some certificates may be unaffected.
