A unikernel's virtio-net device entered `DEVICE_NEEDS_RESET` during operation. Binary memory dumps of the device state at crash time are in `/app/dumps/`. A format reference describing binary layouts is at `/app/dumps/FORMAT.txt`.

The dump includes: common configuration registers, per-queue configs, negotiated feature bits, device-specific network config, three virtqueue descriptor tables and ring buffers, a guest physical memory snapshot, a device event log, and an MSI-X interrupt table.

Produce `/app/analysis_report.json` with this structure:

```json
{
  "device": {
    "mac": "<colon-separated lowercase hex>",
    "status": "<device_status register integer>",
    "mtu": "<integer>",
    "num_queues": "<integer>"
  },
  "features": {
    "word0": "<negotiated features bits 0-31 integer>",
    "word1": "<negotiated features bits 32-63 integer>"
  },
  "queues": [
    {
      "index": "<queue number>",
      "size": "<queue size>",
      "avail_idx": "<avail ring idx field>",
      "used_idx": "<used ring idx field>",
      "errors": [
        {"chain_head": "<head desc index>", "type": "<error classification>", "details": "<specifics>"}
      ]
    }
  ],
  "packets": {
    "tx_sent": [
      {"chain_head": "<int>", "dst_mac": "<MAC>", "src_mac": "<MAC>", "ethertype": "<hex string>"}
    ],
    "rx_received": [
      {"desc_id": "<int>", "dst_mac": "<MAC>", "src_mac": "<MAC>", "ethertype": "<hex string>"}
    ]
  },
  "crash": {
    "cause": "<root cause>",
    "queue_index": "<queue that triggered crash>",
    "timestamp_ns": "<from event log>",
    "msix_issues": [
      {"vector_index": "<int>", "issue": "<description>"}
    ]
  }
}
```

The `queues` array must cover all device queues. For each queue, walk all pending descriptor chains (between `used_idx` and `avail_idx`) through the descriptor table to detect corruption — cycles or invalid references. For `packets`, reconstruct Ethernet headers from successfully completed chains by following descriptors into `guest_memory.bin`. The first descriptor in a virtio-net TX chain is a 12-byte virtio-net header (mergeable rx buffers negotiated); Ethernet data starts in subsequent descriptors. For RX buffers, each starts with a 12-byte virtio-net header followed by the Ethernet frame. Correlate `event_log.bin` with queue state to identify the crash trigger, and inspect `msix_table.bin` for configuration anomalies.