A substation PTP network operating under IEEE C37.238-2011 (Power Profile) has been captured for conformance auditing. Data is at `/app/scenario/`:

- `topology.json` — clock inventory with data-set attributes and network segment map
- `segment1.pcap` — pcap capture from segment 1 monitoring tap (contains mixed PTP and non-PTP traffic; legitimate PTP devices use 802.1Q VLAN tagging with VLAN 100, rogue devices transmit untagged)
- `segment2.pcap` — pcap capture from segment 2 monitoring tap (untagged traffic)
- `capture_log.json` — receive metadata: message ID, pcap file, frame number, receive timestamp, receiver clock/port, and originating source clock

An existing linuxptp (ptp4l) configuration for device GM_B is at `/app/configs/gm_b_ptp4l.conf`. It has multiple IEEE C37.238 Power Profile compliance violations requiring remediation.

NISTIR 8002 reference excerpts are at `/app/reference/`.

Produce:

**1.** `/app/results.json`:

```json
{
  "parsed_fields": {
    "<msg_id>": {
      "message_type": "<int>",
      "domain_number": "<int>",
      "log_message_interval": "<int, signed>",
      "source_clock_identity": "<16-char lowercase hex>",
      "source_port_number": "<int>",
      "gm_priority1": "<int>",
      "clock_class": "<int>",
      "clock_accuracy": "<int>",
      "offset_scaled_log_var": "<int>",
      "gm_priority2": "<int>",
      "gm_identity": "<16-char lowercase hex>",
      "steps_removed": "<int>",
      "alternate_master_flag": "<bool>",
      "two_step_flag": "<bool>",
      "current_utc_offset": "<int>",
      "time_source": "<int>",
      "tlv_gm_time_inaccuracy": "<int>",
      "tlv_network_time_inaccuracy": "<int>"
    }
  },
  "disqualified_messages": { "<msg_id>": "<reason>" },
  "bmca_results": {
    "<clock_name>": {
      "selected_grandmaster": "<clock identity hex>",
      "port_states": { "<port_number>": "MASTER|SLAVE|PASSIVE|LISTENING" }
    }
  },
  "conformance": {
    "<clock_name>": {
      "logAnnounceInterval": "PASS|FAIL|N/A",
      "priority1": "PASS|FAIL|N/A",
      "priority2": "PASS|FAIL|N/A",
      "domainNumber": "PASS|FAIL"
    }
  },
  "timing_stats": {
    "<clock_name>": {
      "mean_interval": "<float>",
      "ci90_low": "<float>",
      "ci90_high": "<float>",
      "conformant": "<bool>"
    }
  },
  "config_violations": {
    "gm_b": {
      "<parameter_name>": {
        "current": "<value as string>",
        "required": "<value as string>"
      }
    }
  }
}
```

**2.** `/app/corrected_gm_b.cfg` — a corrected ptp4l configuration fixing all Power Profile violations found in the original config. Must use standard linuxptp configuration format.

Timing statistics should reflect unique physical transmissions from each source clock (deduplicated by sequence ID), not duplicated observations by multiple receivers on a shared segment.