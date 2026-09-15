BLE Link Layer Encryption Procedure
=====================================

Reference: Bluetooth Core Specification v5.x, Vol 6, Part B, Section 5.1.3

Overview
--------
Link Layer encryption is used to protect data transmitted over a BLE
connection. The encryption procedure is always initiated by the Link Layer
in the Central role. The Peripheral may never initiate encryption.

Encryption Start Procedure
--------------------------
The following sequence establishes encryption on an unencrypted connection:

  1. Central sends LL_ENC_REQ to the Peripheral.
     Contains: Rand (8 bytes), EDIV (2 bytes), SKDm (8 bytes), IVm (4 bytes).
     Rand and EDIV identify which Long Term Key (LTK) should be used.

  2. Peripheral responds with LL_ENC_RSP.
     Contains: SKDs (8 bytes), IVs (4 bytes).
     The Peripheral uses the combined SKD and IV to derive the session key
     and enables receive-path decryption.

  3. Peripheral sends LL_START_ENC_REQ (empty payload).
     Sent after the Peripheral has enabled RX decryption.

  4. Central responds with LL_START_ENC_RSP (empty payload).
     Sent after the Central has enabled both TX encryption and RX decryption.

  5. Peripheral sends LL_START_ENC_RSP (empty payload).
     Confirms that encryption is fully active in both directions.

After step 5, the connection is encrypted.

Ordering constraint: Each step MUST occur in the order listed above.
Receiving a PDU out of the expected order is a protocol violation.

Session Key Derivation
----------------------
Both sides derive the session key from the Long Term Key and the
Session Key Diversifiers exchanged during the procedure:

  SKD = SKDs || SKDm  (16 bytes: SKDs as MSB, SKDm as LSB)
  SK  = e(LTK, SKD)   where e() is AES-128 encryption in ECB mode

The session key SK is used for AES-CCM encryption of data PDUs.

Key Size Negotiation
--------------------
The effective encryption key size is negotiated between the Host and
Controller via HCI. The negotiated key size may be less than 16 bytes
(minimum 7 bytes per specification). When the key size is less than
16 bytes, only the first N bytes of the session key are cryptographically
significant.

This negotiation is NOT visible at the Link Layer — it occurs between
the Host and Controller via the HCI Read Encryption Key Size command
and response. A reduced key size weakens the effective encryption
strength (CVE-2019-9506, commonly known as the KNOB attack).

HCI-LL Correlation
------------------
The Host Controller Interface (HCI) carries encryption-related events
that provide metadata not available at the Link Layer:

- LE Long Term Key Request: The Controller requests the LTK from the
  Host, including the Rand and EDIV values from the received LL_ENC_REQ.
  These values can be used to correlate HCI events with LL-level PDUs
  across captures from different protocol layers.

- Encryption Change: Confirms encryption activation for a connection
  handle.

- Read Encryption Key Size: Returns the effective key size negotiated
  for a specific connection handle.

Connection handles in HCI events identify connections. To correlate
an LL capture with HCI data, match the Rand and EDIV values that
appear in both the LL_ENC_REQ PDU and the HCI LE Long Term Key
Request event.

Encryption Pause and Restart Procedure
---------------------------------------
To change the encryption key on an already-encrypted connection, the Link
Layer uses the pause procedure followed by a new encryption start:

  1. Central sends LL_PAUSE_ENC_REQ to the Peripheral.
  2. Peripheral responds with LL_PAUSE_ENC_RSP.
     Peripheral disables RX decryption and TX encryption.
  3. Central sends LL_PAUSE_ENC_RSP.
     Central disables RX decryption and TX encryption.

After step 3, the connection is unencrypted. The Central then initiates
a new Encryption Start Procedure (LL_ENC_REQ, etc.) with the new key.

Timeout Constraint
------------------
The entire encryption start procedure (from LL_ENC_REQ to the final
LL_START_ENC_RSP) MUST complete within 40 seconds. If the procedure
has not completed within this window, it is considered a timeout violation
(Bluetooth Core Spec Vol 6, Part B, Section 5.1.3).

Connection Termination
----------------------
LL_TERMINATE_IND may be sent at any time to terminate the connection.
However, sending LL_TERMINATE_IND while an encryption procedure is
in progress (i.e., after LL_ENC_REQ has been sent but before the final
LL_START_ENC_RSP, or during the pause procedure) is abnormal behavior
that should be flagged.

Direction Rules
---------------
- LL_ENC_REQ: Central -> Peripheral ONLY
- LL_ENC_RSP: Peripheral -> Central ONLY
- LL_START_ENC_REQ: Peripheral -> Central ONLY
- LL_START_ENC_RSP (step 4): Central -> Peripheral
- LL_START_ENC_RSP (step 5): Peripheral -> Central
- LL_PAUSE_ENC_REQ: Central -> Peripheral ONLY
- LL_PAUSE_ENC_RSP (step 2): Peripheral -> Central
- LL_PAUSE_ENC_RSP (step 3): Central -> Peripheral
