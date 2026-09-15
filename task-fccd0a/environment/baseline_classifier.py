"""Baseline packet classifier -- parses nftables ruleset, first-match linear scan."""
import re


class BaselineClassifier:
    def __init__(self, ruleset_path):
        self.rules = self._parse_nft(ruleset_path)

    def _parse_nft(self, path):
        rules = []
        with open(path) as f:
            lines = f.readlines()

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            m = re.match(r'# rule_id=(\d+)', line)
            if m:
                rule_id = int(m.group(1))
                i += 1
                if i < len(lines):
                    rule_line = lines[i].strip()
                    rule = self._parse_rule_line(rule_id, rule_line)
                    if rule:
                        rules.append(rule)
            i += 1

        return rules

    def _parse_rule_line(self, rule_id, line):
        rule = {
            "id": rule_id,
            "src_ip": "0.0.0.0/0",
            "dst_ip": "0.0.0.0/0",
            "src_port_min": 0, "src_port_max": 65535,
            "dst_port_min": 0, "dst_port_max": 65535,
            "protocol": "any",
            "action": "accept"
        }

        line = re.sub(r'\bcounter\b', '', line).strip()

        m = re.search(r'ip saddr (\S+)', line)
        if m:
            rule["src_ip"] = m.group(1)

        m = re.search(r'ip daddr (\S+)', line)
        if m:
            rule["dst_ip"] = m.group(1)

        for proto in ["tcp", "udp"]:
            m = re.search(rf'{proto} sport (\d+)(?:-(\d+))?', line)
            if m:
                rule["protocol"] = proto
                rule["src_port_min"] = int(m.group(1))
                rule["src_port_max"] = int(m.group(2)) if m.group(2) else int(m.group(1))

            m = re.search(rf'{proto} dport (\d+)(?:-(\d+))?', line)
            if m:
                rule["protocol"] = proto
                rule["dst_port_min"] = int(m.group(1))
                rule["dst_port_max"] = int(m.group(2)) if m.group(2) else int(m.group(1))

        words = line.split()
        if words:
            action = words[-1]
            if action in ("accept", "drop", "log"):
                rule["action"] = action

        return rule

    def _ip_to_int(self, ip_str):
        parts = ip_str.split(".")
        return (int(parts[0]) << 24) | (int(parts[1]) << 16) | (int(parts[2]) << 8) | int(parts[3])

    def _ip_in_cidr(self, ip_str, cidr_str):
        ip_int = self._ip_to_int(ip_str)
        net_str, plen = cidr_str.rsplit("/", 1)
        plen = int(plen)
        if plen == 0:
            return True
        net_int = self._ip_to_int(net_str)
        shift = 32 - plen
        return (ip_int >> shift) == (net_int >> shift)

    def _matches(self, packet, rule):
        if not self._ip_in_cidr(packet["src_ip"], rule["src_ip"]):
            return False
        if not self._ip_in_cidr(packet["dst_ip"], rule["dst_ip"]):
            return False
        if not (rule["src_port_min"] <= packet["src_port"] <= rule["src_port_max"]):
            return False
        if not (rule["dst_port_min"] <= packet["dst_port"] <= rule["dst_port_max"]):
            return False
        if rule["protocol"] != "any" and rule["protocol"] != packet["protocol"]:
            return False
        return True

    def classify(self, packet):
        for rule in self.rules:
            if self._matches(packet, rule):
                return rule["action"], rule["id"]
        return "drop", -1
