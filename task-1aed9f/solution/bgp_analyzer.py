#!/usr/bin/env python3
"""BGP Route Analyzer — Solution Implementation.

Integrates data from SQLite database, PCAP capture, and JSON config.

"""
import json
import socket
import sqlite3
import struct
import sys
import os


# -------------------------------------------------------------------
# Core algorithm
# -------------------------------------------------------------------

def _ip_to_int(ip):
    parts = ip.split(".")
    return (int(parts[0]) << 24) | (int(parts[1]) << 16) | (int(parts[2]) << 8) | int(parts[3])


def _as_path_length(as_path):
    length = 0
    for seg in as_path:
        t = seg["type"]
        if t == "AS_SEQUENCE":
            length += len(seg["asns"])
        elif t == "AS_SET":
            length += 1
    return length


def _neighbor_as(as_path):
    for seg in as_path:
        if seg["type"] in ("AS_CONFED_SEQUENCE", "AS_CONFED_SET"):
            continue
        if seg["type"] in ("AS_SEQUENCE", "AS_SET") and seg["asns"]:
            return seg["asns"][0]
    return None


def _is_confed_only(as_path):
    for seg in as_path:
        if seg["type"] not in ("AS_CONFED_SEQUENCE", "AS_CONFED_SET"):
            return False
    return True


def _origin_val(o):
    return {"igp": 0, "egp": 1, "incomplete": 2}.get(o, 2)


def _effective_med(route, config):
    med = route.get("med")
    if med is None:
        return 4294967295 if config.get("med_missing_as_worst") else 0
    return med


def _is_external(route):
    return route.get("path_source") == "ebgp"


def _effective_rid(route):
    oid = route.get("originator_id")
    return oid if oid else route.get("router_id", "0.0.0.0")


def _compare(a, b, config):
    """Return -1 if a is better, +1 if b is better, 0 if tied."""
    # Step 1: weight
    aw, bw = a.get("weight", 0), b.get("weight", 0)
    if aw != bw:
        return -1 if aw > bw else 1

    # Step 2: local_pref
    alp = a.get("local_pref") if a.get("local_pref") is not None else 100
    blp = b.get("local_pref") if b.get("local_pref") is not None else 100
    if alp != blp:
        return -1 if alp > blp else 1

    # Step 3: locally originated
    al = a.get("locally_originated", False)
    bl = b.get("locally_originated", False)
    if al != bl:
        return -1 if al else 1
    if al and bl:
        tp = {"network": 0, "redistribute": 0, "aggregate": 1}
        ap = tp.get(a.get("local_origin_type", "network"), 1)
        bp = tp.get(b.get("local_origin_type", "network"), 1)
        if ap != bp:
            return -1 if ap < bp else 1

    # Step 4: AS-path length
    if not config.get("as_path_ignore"):
        al_ = _as_path_length(a.get("as_path", []))
        bl_ = _as_path_length(b.get("as_path", []))
        if al_ != bl_:
            return -1 if al_ < bl_ else 1

    # Step 5: origin
    ao = _origin_val(a.get("origin", "incomplete"))
    bo = _origin_val(b.get("origin", "incomplete"))
    if ao != bo:
        return -1 if ao < bo else 1

    # Step 6: MED
    do_med = False
    if config.get("always_compare_med"):
        do_med = True
    elif (config.get("med_confed")
          and _is_confed_only(a.get("as_path", []))
          and _is_confed_only(b.get("as_path", []))):
        do_med = True
    else:
        na = _neighbor_as(a.get("as_path", []))
        nb = _neighbor_as(b.get("as_path", []))
        if na is not None and nb is not None and na == nb:
            do_med = True

    if do_med:
        am = _effective_med(a, config)
        bm = _effective_med(b, config)
        if am != bm:
            return -1 if am < bm else 1

    # Step 7: eBGP > iBGP
    ae = _is_external(a)
    be = _is_external(b)
    if ae != be:
        return -1 if ae else 1

    # Step 8: IGP metric
    ai = a.get("igp_metric", 0)
    bi = b.get("igp_metric", 0)
    if ai != bi:
        return -1 if ai < bi else 1

    # Step 10: oldest path
    if not config.get("compare_routerid"):
        if ae and be:
            a_eff = _effective_rid(a)
            b_eff = _effective_rid(b)
            if a_eff != b_eff:
                aa = a.get("arrival_order", 0)
                ba = b.get("arrival_order", 0)
                if aa != ba:
                    return -1 if aa < ba else 1

    # Step 11: router ID (originator_id substituted)
    ar = _ip_to_int(_effective_rid(a))
    br = _ip_to_int(_effective_rid(b))
    if ar != br:
        return -1 if ar < br else 1

    # Step 12: cluster list length
    acl = len(a.get("cluster_list", []))
    bcl = len(b.get("cluster_list", []))
    if acl != bcl:
        return -1 if acl < bcl else 1

    # Step 13: neighbor address
    an = _ip_to_int(a.get("neighbor_address", "0.0.0.0"))
    bn = _ip_to_int(b.get("neighbor_address", "0.0.0.0"))
    if an != bn:
        return -1 if an < bn else 1

    return 0


def select_best_path(routes, config):
    """Select the best BGP path from candidate routes."""
    valid = [(i, r) for i, r in enumerate(routes) if r.get("is_valid", True)]
    if not valid:
        return -1

    if config.get("deterministic_med"):
        return _det_med(config, valid)

    best_i, best_r = valid[0]
    for i, r in valid[1:]:
        if _compare(best_r, r, config) > 0:
            best_i, best_r = i, r
    return best_i


def _det_med(config, valid):
    groups = {}
    for i, r in valid:
        nas = _neighbor_as(r.get("as_path", []))
        groups.setdefault(nas, []).append((i, r))

    winners = []
    for _, grp in groups.items():
        bi, br = grp[0]
        for i, r in grp[1:]:
            if _compare(br, r, config) > 0:
                bi, br = i, r
        winners.append((bi, br))

    bi, br = winners[0]
    for i, r in winners[1:]:
        if _compare(br, r, config) > 0:
            bi, br = i, r
    return bi


# -------------------------------------------------------------------
# PCAP parser — extract BGP UPDATE route data
# -------------------------------------------------------------------

def _parse_pcap(pcap_path):
    """Parse PCAP file and extract BGP UPDATE attributes.

    Returns dict mapping source IP → {origin, med, as_path, nlri_prefix}.
    """
    seg_type_map = {1: 'AS_SET', 2: 'AS_SEQUENCE', 3: 'AS_CONFED_SEQUENCE', 4: 'AS_CONFED_SET'}
    origin_map = {0: 'igp', 1: 'egp', 2: 'incomplete'}
    results = {}

    with open(pcap_path, 'rb') as f:
        # Global header (24 bytes)
        ghdr = f.read(24)
        if len(ghdr) < 24:
            return results

        while True:
            phdr = f.read(16)
            if len(phdr) < 16:
                break
            _, _, incl_len, _ = struct.unpack('<IIII', phdr)
            pkt = f.read(incl_len)
            if len(pkt) < incl_len:
                break

            # Ethernet(14) + IP(20) + TCP(20) = 54 bytes minimum
            if len(pkt) < 54:
                continue

            # Source IP from IP header (bytes 14-33)
            src_ip = socket.inet_ntoa(pkt[26:30])

            # TCP data offset (byte 46, upper 4 bits)
            tcp_data_offset = ((pkt[46] >> 4) & 0xF) * 4
            bgp_start = 14 + 20 + tcp_data_offset

            if len(pkt) < bgp_start + 19:
                continue

            bgp = pkt[bgp_start:]

            # Verify BGP marker (16 bytes of 0xFF)
            if bgp[:16] != b'\xff' * 16:
                continue

            bgp_len, bgp_type = struct.unpack('!HB', bgp[16:19])
            if bgp_type != 2:  # Not UPDATE
                continue

            body = bgp[19:]

            # Withdrawn routes length
            if len(body) < 2:
                continue
            withdrawn_len = struct.unpack('!H', body[:2])[0]
            pos = 2 + withdrawn_len

            if len(body) < pos + 2:
                continue
            total_pa_len = struct.unpack('!H', body[pos:pos + 2])[0]
            pos += 2
            pa_end = pos + total_pa_len

            origin = None
            med = None
            as_path = []

            while pos < pa_end and pos < len(body):
                if pos + 2 > len(body):
                    break
                flags = body[pos]
                type_code = body[pos + 1]

                if flags & 0x10:  # Extended length
                    if pos + 4 > len(body):
                        break
                    attr_len = struct.unpack('!H', body[pos + 2:pos + 4])[0]
                    pos += 4
                else:
                    if pos + 3 > len(body):
                        break
                    attr_len = body[pos + 2]
                    pos += 3

                if pos + attr_len > len(body):
                    break
                attr_val = body[pos:pos + attr_len]

                if type_code == 1 and attr_len >= 1:  # ORIGIN
                    origin = origin_map.get(attr_val[0], 'incomplete')
                elif type_code == 2:  # AS_PATH
                    ap_pos = 0
                    while ap_pos + 2 <= len(attr_val):
                        st = attr_val[ap_pos]
                        sc = attr_val[ap_pos + 1]
                        ap_pos += 2
                        asns = []
                        for _ in range(sc):
                            if ap_pos + 2 > len(attr_val):
                                break
                            asn = struct.unpack('!H', attr_val[ap_pos:ap_pos + 2])[0]
                            asns.append(asn)
                            ap_pos += 2
                        as_path.append({"type": seg_type_map.get(st, 'AS_SEQUENCE'), "asns": asns})
                elif type_code == 4 and attr_len >= 4:  # MED
                    med = struct.unpack('!I', attr_val[:4])[0]

                pos += attr_len

            # NLRI
            nlri_data = body[pa_end:]
            nlri_prefix = None
            if nlri_data and len(nlri_data) >= 1:
                pfx_len = nlri_data[0]
                pfx_bytes = (pfx_len + 7) // 8
                if 1 + pfx_bytes <= len(nlri_data):
                    raw = nlri_data[1:1 + pfx_bytes] + b'\x00' * (4 - pfx_bytes)
                    nlri_prefix = socket.inet_ntoa(raw) + f'/{pfx_len}'

            results[src_ip] = {
                'origin': origin,
                'med': med,
                'as_path': as_path,
                'nlri': nlri_prefix,
            }

    return results


# -------------------------------------------------------------------
# JSON config reader
# -------------------------------------------------------------------

def _load_config_from_json(json_path, config_id):
    """Load config profile flags from nested JSON file."""
    with open(json_path) as f:
        data = json.load(f)

    profiles = data['router_config']['bgp_selection']['profiles']
    for profile in profiles:
        if profile['id'] == config_id:
            return profile['flags']
    return {}


# -------------------------------------------------------------------
# Database reader
# -------------------------------------------------------------------

def _decode_blob(blob):
    """Decode extended_attrs BLOB → (originator_id, cluster_list)."""
    if blob is None or len(blob) == 0:
        return None, []
    flags = blob[0]
    pos = 1
    originator_id = None
    cluster_list = []
    if flags & 0x01:
        originator_id = f"{blob[pos]}.{blob[pos+1]}.{blob[pos+2]}.{blob[pos+3]}"
        pos += 4
    if flags & 0x02:
        count = blob[pos]
        pos += 1
        for _ in range(count):
            cid = f"{blob[pos]}.{blob[pos+1]}.{blob[pos+2]}.{blob[pos+3]}"
            cluster_list.append(cid)
            pos += 4
    return originator_id, cluster_list


def _load_routes_for_prefix(conn, prefix_id, pcap_data, prefix_network):
    """Load all routes for a prefix, supplementing PCAP routes."""
    cur = conn.cursor()
    cur.execute("SELECT * FROM routes WHERE prefix_id=? ORDER BY id", (prefix_id,))
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()

    # Load PCAP route IDs
    cur2 = conn.cursor()
    cur2.execute("SELECT route_id FROM pcap_routes")
    pcap_route_ids = {row[0] for row in cur2.fetchall()}

    result = []
    for row in rows:
        rd = dict(zip(cols, row))
        route_id = rd["id"]

        # Decode BLOB
        oid, clist = _decode_blob(rd.get("extended_attrs"))

        # Load AS path segments from database
        cur3 = conn.cursor()
        cur3.execute(
            "SELECT seg_type, asns FROM as_path_segments WHERE route_id=? ORDER BY seg_order",
            (route_id,),
        )
        as_path = []
        for stype, asns_str in cur3.fetchall():
            asns = [int(x) for x in asns_str.split(",") if x]
            as_path.append({"type": stype, "asns": asns})

        origin = rd["origin"]
        med = rd["med"]

        # Supplement from PCAP if this is a PCAP-sourced route
        if route_id in pcap_route_ids:
            neighbor = rd["neighbor_address"]
            if neighbor in pcap_data:
                pd = pcap_data[neighbor]
                # Verify NLRI matches the prefix
                if pd.get('nlri') and prefix_network and pd['nlri'] == prefix_network:
                    if pd['origin'] is not None:
                        origin = pd['origin']
                    if pd['med'] is not None:
                        med = pd['med']
                    if pd['as_path']:
                        as_path = pd['as_path']

        route = {
            "weight": rd["weight"],
            "local_pref": rd["local_pref"],
            "locally_originated": bool(rd["locally_originated"]),
            "local_origin_type": rd.get("local_origin_type"),
            "as_path": as_path,
            "origin": origin,
            "med": med,
            "path_source": rd["path_source"],
            "igp_metric": rd["igp_metric"],
            "router_id": rd["router_id"],
            "originator_id": oid,
            "cluster_list": clist,
            "neighbor_address": rd["neighbor_address"],
            "is_valid": bool(rd["is_valid"]),
            "arrival_order": rd["arrival_order"],
            "_db_id": route_id,
        }
        result.append(route)
    return result


def analyze(db_path, pcap_path, config_json_path):
    """Analyze all queries and return {query_id: best_route_id}."""
    # Parse PCAP
    pcap_data = _parse_pcap(pcap_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, prefix_id, config_id FROM queries ORDER BY id")
    queries = cur.fetchall()

    results = {}
    for qid, pid, cid in queries:
        # Get prefix network for NLRI matching
        cur2 = conn.cursor()
        cur2.execute("SELECT network FROM prefixes WHERE id=?", (pid,))
        prefix_network = cur2.fetchone()[0]

        routes = _load_routes_for_prefix(conn, pid, pcap_data, prefix_network)
        config = _load_config_from_json(config_json_path, cid)
        best_idx = select_best_path(routes, config)
        if best_idx >= 0:
            results[str(qid)] = routes[best_idx]["_db_id"]
        else:
            results[str(qid)] = -1

    conn.close()
    return results


def main():
    db_path = "/app/bgp_rib.db"
    pcap_path = "/app/bgp_capture.pcap"
    config_json = "/app/policies/selection.json"
    results = analyze(db_path, pcap_path, config_json)
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
