"""Adaptive firewall classifier with locality-aware rule reordering,
unreachable rule detection, and ordering constraint analysis."""

import re


class AdaptiveClassifier:
    def __init__(self, ruleset_path):
        self._original_rules = self._parse_nft(ruleset_path)
        self._rules = list(self._original_rules)
        self._unreachable = self._compute_unreachable()
        self._constraints = self._compute_ordering_constraints()
        self._minimal = self._compute_minimal_constraints()
        self._constraint_set = set((a, b) for a, b in self._constraints)

    # ===== Parsing =====

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

    # ===== IP / Match Utilities =====

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

    def _cidrs_overlap(self, cidr_a, cidr_b):
        net_a, plen_a = cidr_a.rsplit("/", 1)
        net_b, plen_b = cidr_b.rsplit("/", 1)
        plen_a, plen_b = int(plen_a), int(plen_b)
        if plen_a == 0 or plen_b == 0:
            return True
        a = self._ip_to_int(net_a)
        b = self._ip_to_int(net_b)
        min_p = min(plen_a, plen_b)
        shift = 32 - min_p
        return (a >> shift) == (b >> shift)

    def _cidr_contains(self, outer, inner):
        net_o, plen_o = outer.rsplit("/", 1)
        net_i, plen_i = inner.rsplit("/", 1)
        plen_o, plen_i = int(plen_o), int(plen_i)
        if plen_o == 0:
            return True
        if plen_i < plen_o:
            return False
        o = self._ip_to_int(net_o)
        i = self._ip_to_int(net_i)
        shift = 32 - plen_o
        return (o >> shift) == (i >> shift)

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

    # ===== Unreachable Rule Detection =====

    def _rule_is_superset(self, ra, rb):
        if not self._cidr_contains(ra["src_ip"], rb["src_ip"]):
            return False
        if not self._cidr_contains(ra["dst_ip"], rb["dst_ip"]):
            return False
        if not (ra["src_port_min"] <= rb["src_port_min"] and rb["src_port_max"] <= ra["src_port_max"]):
            return False
        if not (ra["dst_port_min"] <= rb["dst_port_min"] and rb["dst_port_max"] <= ra["dst_port_max"]):
            return False
        if ra["protocol"] != "any" and ra["protocol"] != rb["protocol"]:
            return False
        return True

    def _compute_unreachable(self):
        unreachable = []
        for j in range(len(self._original_rules)):
            for i in range(j):
                if self._rule_is_superset(self._original_rules[i], self._original_rules[j]):
                    unreachable.append(self._original_rules[j]["id"])
                    break
        return sorted(unreachable)

    # ===== Ordering Constraint Analysis =====

    def _rules_overlap(self, ra, rb):
        if not self._cidrs_overlap(ra["src_ip"], rb["src_ip"]):
            return False
        if not self._cidrs_overlap(ra["dst_ip"], rb["dst_ip"]):
            return False
        if ra["src_port_max"] < rb["src_port_min"] or rb["src_port_max"] < ra["src_port_min"]:
            return False
        if ra["dst_port_max"] < rb["dst_port_min"] or rb["dst_port_max"] < ra["dst_port_min"]:
            return False
        pa, pb = ra["protocol"], rb["protocol"]
        if pa != "any" and pb != "any" and pa != pb:
            return False
        return True

    def _compute_ordering_constraints(self):
        constraints = []
        for i in range(len(self._original_rules)):
            for j in range(i + 1, len(self._original_rules)):
                if self._original_rules[i]["action"] != self._original_rules[j]["action"]:
                    if self._rules_overlap(self._original_rules[i], self._original_rules[j]):
                        constraints.append((self._original_rules[i]["id"], self._original_rules[j]["id"]))
        return constraints

    def _compute_minimal_constraints(self):
        all_ids = set(r["id"] for r in self._original_rules)
        adj = {n: set() for n in all_ids}
        for a, b in self._constraints:
            adj[a].add(b)

        minimal = []
        for u, v in self._constraints:
            reachable = set()
            queue = []
            for w in adj[u]:
                if w != v and w not in reachable:
                    reachable.add(w)
                    queue.append(w)
            idx = 0
            while idx < len(queue):
                node = queue[idx]
                idx += 1
                for neighbor in adj[node]:
                    if neighbor not in reachable:
                        reachable.add(neighbor)
                        queue.append(neighbor)
            if v not in reachable:
                minimal.append((u, v))

        return minimal

    # ===== Classification =====

    def classify(self, packet):
        matched_pos = None
        for i, rule in enumerate(self._rules):
            if self._matches(packet, rule):
                matched_pos = i
                break

        if matched_pos is None:
            return "drop", -1

        result = (self._rules[matched_pos]["action"], self._rules[matched_pos]["id"])

        # Promote matched rule toward front, stopping at constraint barriers
        pos = matched_pos
        while pos > 0:
            front_id = self._rules[pos - 1]["id"]
            back_id = self._rules[pos]["id"]
            if (front_id, back_id) in self._constraint_set:
                break
            self._rules[pos - 1], self._rules[pos] = self._rules[pos], self._rules[pos - 1]
            pos -= 1

        return result

    # ===== Public API =====

    def get_rule_order(self):
        return [r["id"] for r in self._rules]

    def get_unreachable_rules(self):
        return list(self._unreachable)

    def get_ordering_constraints(self):
        return list(self._constraints)

    def get_minimal_constraints(self):
        return list(self._minimal)
