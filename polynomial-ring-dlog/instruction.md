A custom key exchange protocol ("CryptoExchange") implements Diffie-Hellman over the polynomial ring GF(2)[x] / f(x). A session between two parties was captured on the network.

You are given:
- `/app/capture.pcap` — a network capture containing the key exchange session intermixed with other unrelated traffic (DNS, HTTP, TLS)
- `/app/protocol.py` — the full protocol implementation including the binary wire format, GF(2) polynomial arithmetic, and key derivation logic

Your goal is to recover the plaintext message that was encrypted during this key exchange session. Write the recovered plaintext to `/app/flag.txt`.

The key exchange protocol operates on TCP port 31337 and uses a binary TLV wire format documented in the protocol source. The system has `tshark`, `openssl`, and `python3` available. You will need to extract the protocol data from the network capture, analyze the cryptographic parameters, and break the key exchange to recover the encryption key.

The flag format is `FLAG{...}`.