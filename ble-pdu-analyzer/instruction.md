An nRF52840-based BLE peripheral ("Nordic_HRM") is failing to be discovered by central devices. Debugging artifacts are in `/app/`:

- `/app/captures/` — BLE advertisement channel PDU captures from channels 37, 38, and 39 (each channel was exported using a different tool, resulting in different file encodings that must be identified)
- `/app/firmware/` — device BLE configuration and serial output logs
- `/app/tools/dissector.py` — a colleague's BLE PDU dissector (contains bugs that produce incorrect results)

Investigate all capture files, determine each file's encoding, fix the dissector or write a correct parser, and produce `/app/diagnostic_report.json`. Parse all PDUs per the Bluetooth Core Specification v5.4 (Vol 6, Part B — Link Layer advertisement channel PDUs). Detect specification violations.

## Output: `/app/diagnostic_report.json`

JSON with keys `pdus` (array) and `summary` (object).

**PDU entry fields:** `pdu_type` (e.g. `"ADV_IND"`), `tx_addr_type` (`"public"`/`"random"`), `advertiser_address` (colon-separated uppercase hex), `ad_structures` (array), `violations` (array of strings). Include `target_address` only for `ADV_DIRECT_IND`.

**AD structure fields:** `ad_type` (int), `ad_type_name` (string), `parsed` (object). Parsed formats by type: Flags — `{le_limited_discoverable, le_general_discoverable, bredr_not_supported}` as booleans; Names — `{name}`; TX Power — `{tx_power_dbm}` as signed int; 16-bit UUIDs — `{uuids}` as 4-char uppercase hex; 128-bit UUIDs — `{uuids}` in standard UUID format; MSD — `{company_id, msd_data_hex}` with `company_id` as 4-char uppercase hex; Service Data — `{service_uuid, service_data_hex}`; Appearance — `{appearance}` as int.

**Summary fields:** `total_pdus`, `valid_pdus` (zero violations), `invalid_pdus`, `pdu_type_counts` (dict), `unique_advertisers`, `nordic_msd_count` (PDUs with MSD Company ID `"0059"`), `total_violations`.