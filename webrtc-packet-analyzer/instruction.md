Two network taps at different points captured halves of a WebRTC session flagged for security review. The captures are at `/app/captures/tap_alpha.pcap` (outbound traffic from endpoint A at 10.0.0.1:50000) and `/app/captures/tap_beta.pcap` (outbound traffic from endpoint B at 10.0.0.2:50001 plus an unidentified third party). Both are libpcap format.

Session ICE credentials and RTP codec clock rates are in `/app/session_config.json`. The config file's HMAC-SHA256 integrity signature is at `/app/session_integrity.hmac` (hex-encoded digest), with the HMAC key stored in `/app/hmac_key.txt`.

Reconstruct the full session by merging the two captures into `/app/merged.pcap`, verify the session config's cryptographic integrity, extract per-capture metadata, and perform complete protocol-level analysis on the merged traffic. Produce `/app/report.json`:

```json
{
  "capture_info": {
    "tap_alpha_packets": "<int: packet count from tap_alpha.pcap>",
    "tap_beta_packets": "<int: packet count from tap_beta.pcap>",
    "merged_total_packets": "<int: total packets in merged capture>",
    "capture_duration_sec": "<float: time span from first to last packet in merged capture>"
  },
  "session_integrity": {
    "config_hmac_valid": "<bool: true if HMAC-SHA256 of session_config.json matches the signature>"
  },
  "packet_counts": {
    "total": "<int>",
    "stun": "<int>",
    "dtls": "<int>",
    "rtp": "<int>",
    "rtcp": "<int>",
    "unknown": "<int>"
  },
  "stun_analysis": {
    "binding_requests": "<int>",
    "binding_responses": "<int>",
    "integrity_valid": "<int>",
    "integrity_invalid": "<int>",
    "nominated_pair": {
      "src": "<ip:port>",
      "dst": "<ip:port>"
    }
  },
  "rtp_analysis": {
    "<ssrc_hex>": {
      "packet_count": "<int>",
      "loss_count": "<int>",
      "loss_rate": "<float>",
      "jitter": "<float>",
      "duration_ms": "<float>",
      "first_seq": "<int>",
      "last_seq": "<int>"
    }
  },
  "rtcp_analysis": {
    "sender_reports": "<int>",
    "receiver_reports": "<int>"
  }
}
```

SSRC keys must be lowercase hex with `0x` prefix (e.g., `"0x12345678"`). Jitter values are interarrival jitter in RTP timestamp units. Loss count is the number of missing sequence numbers within the observed sequence number range. STUN MESSAGE-INTEGRITY must be verified using ICE short-term credential mechanics — the first fragment of the USERNAME attribute identifies which password to use.