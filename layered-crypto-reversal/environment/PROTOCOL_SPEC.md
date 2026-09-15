# Secure Transport Protocol v2 — Technical Specification

## CLASSIFICATION: TLP:AMBER
## Version: 2.1 | Last Updated: 2024-09-15

## 1. Overview

STP v2 provides data confidentiality using **RSA-4096** asymmetric key encapsulation
combined with **AES-256** symmetric block encryption in configurable cipher modes.
All implementations MUST use OAEP padding for RSA operations per PKCS#1 v2.1.

## 2. Transport

All protocol messages are carried over UDP. The default server port is **9999**.

## 3. Message Format

All messages share a common 6-byte header:

| Offset | Size  | Field             | Description                  |
|--------|-------|-------------------|------------------------------|
| 0      | 4     | Magic             | ASCII `PROT` (0x50524F54)    |
| 4      | 1     | Version           | Protocol version (0x02)      |
| 5      | 1     | MessageType       | See Section 4                |
| 6+     | var   | Payload           | Type-specific payload        |

## 4. Message Types

### 4.1 ClientHello (0x01)

Sent by the client to initiate the handshake.

| Offset | Size | Field          |
|--------|------|----------------|
| 0      | 1    | NumModes       |
| 1      | N    | SupportedModes |
| 1+N    | 16   | ClientRandom   |

### 4.2 ServerHello (0x02)

Server response selecting cipher parameters.

| Offset | Size | Field          |
|--------|------|----------------|
| 0      | 1    | SelectedMode   |
| 1      | 16   | IV             |
| 17     | 16   | ServerRandom   |

The IV length matches the AES block size (16 bytes).

### 4.3 KeyExchange (0x03)

Client sends the RSA-OAEP encapsulated session key.

| Offset | Size | Field              |
|--------|------|--------------------|
| 0      | 2    | CiphertextLength   |
| 2      | N    | RSACiphertext      |

The plaintext encapsulated under RSA-OAEP is:
```
M = "PROTO_V2_SESSKEY" || K
```
where K is the 32-byte AES-256 session key.

### 4.4 DataTransfer (0x04)

Encrypted payload transmission.

| Offset | Size | Field            |
|--------|------|------------------|
| 0      | var  | EncryptedPayload |

## 5. Cipher Modes

Three AES-256 block cipher modes are supported:

| Mode | Name | Description |
|------|------|-------------|
| 0    | ECB  | Electronic Codebook — each 16-byte block encrypted independently |
| 1    | CBC  | Cipher Block Chaining — standard IV-based chaining (RECOMMENDED) |
| 2    | PCBC | Propagating CBC — error-propagation mode, feedback = P_i XOR C_i |

All modes use **PKCS#7 padding** to the 16-byte AES block boundary.

PCBC decryption formula:
```
P_i = D_K(C_i) XOR feedback_i
feedback_{i+1} = P_i XOR C_i
feedback_0 = IV
```

## 6. Security Parameters

| Parameter       | Value                  |
|-----------------|------------------------|
| RSA key size    | 4096 bits              |
| RSA padding     | OAEP (PKCS#1 v2.1)    |
| Symmetric cipher| AES-256                |
| Block size      | 16 bytes               |
| Session key     | 32 bytes (256 bits)    |

## 7. Compliance

This protocol is designed to meet NIST SP 800-56B Rev. 2 requirements for
key transport and NIST SP 800-38A for block cipher modes of operation.

Mode 1 (CBC) is the RECOMMENDED default for general use.
Mode 2 (PCBC) is provided for legacy compatibility only.
