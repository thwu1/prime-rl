#!/usr/bin/env python3
"""
SIP Application Level Gateway (ALG) Connection Tracker Simulator

Simulates the behavior of Linux netfilter's nf_conntrack_sip module.
Processes TCP segments and detects SIP signaling messages at segment
boundaries to create firewall expectations (pinholes).

Based on the connection tracking behavior documented in:
- Linux kernel nf_conntrack_sip.c (process_sip_request / process_sip_msg)
- RFC 3261 (SIP: Session Initiation Protocol)

"""

import re
import sys


class SIPConnectionTracker:
    """
    Models nf_conntrack_sip behavior for TCP streams.

    Key behaviors modeled:
    - strncasecmp of SIP method at byte offset 0 of each TCP segment
    - SIP request-line validation (METHOD sip:... SIP/2.0)
    - Contact header extraction and IP validation against connection source
    - Rejection of IPs with leading-zero octets
    - Optional strict mode requiring Via, Call-ID, CSeq, Expires, Max-Forwards
    """

    _PINHOLE_METHODS = frozenset(['REGISTER', 'INVITE'])

    _ALL_METHODS = frozenset([
        'REGISTER', 'INVITE', 'ACK', 'BYE', 'CANCEL',
        'OPTIONS', 'PRACK', 'SUBSCRIBE', 'NOTIFY', 'PUBLISH',
        'INFO', 'REFER', 'MESSAGE', 'UPDATE'
    ])

    def __init__(self, strict=False, debug=False):
        self.strict = strict
        self.debug = debug
        self.expectations = []
        self._log = []

    def process_stream(self, segments, expected_src_ip):
        """
        Process a segmented TCP stream.

        Args:
            segments: List of bytes objects representing TCP segments
            expected_src_ip: Internal IP that must match Contact header

        Returns:
            List of expectation dicts:
              {segment_index, method, contact_ip, contact_port, user}
        """
        self.expectations = []
        self._log = []

        for idx, seg in enumerate(segments):
            self._dbg(f"[seg {idx}] len={len(seg)} "
                       f"first_bytes={seg[:50]!r}")
            self._process_segment(seg, expected_src_ip, idx)

        return list(self.expectations)

    # ── segment processing ──────────────────────────────────────────

    def _process_segment(self, segment, expected_src_ip, seg_idx):
        try:
            text = segment.decode('utf-8')
        except UnicodeDecodeError:
            self._dbg("  -> non-UTF8, skip")
            return

        method = self._match_method(text)
        if method is None:
            self._dbg("  -> no SIP method at offset 0")
            return

        self._dbg(f"  -> matched method: {method}")

        if method not in self._PINHOLE_METHODS:
            self._dbg(f"  -> {method} does not create expectations")
            return

        # ── request-line ────────────────────────────────────────────
        rl_end = text.find('\r\n')
        if rl_end < 0:
            self._dbg("  -> no CRLF terminating request line")
            return

        if not self._validate_request_line(text[:rl_end], method):
            self._dbg(f"  -> invalid request line")
            return

        # ── headers (must complete within this segment) ─────────────
        hdr_end = text.find('\r\n\r\n')
        if hdr_end < 0:
            self._dbg("  -> header section not complete in segment")
            return

        headers = self._parse_headers(text[rl_end + 2 : hdr_end])

        # ── Contact ─────────────────────────────────────────────────
        contact = headers.get('contact')
        if not contact:
            self._dbg("  -> missing Contact header")
            return

        parsed = self._parse_contact(contact)
        if parsed is None:
            self._dbg(f"  -> invalid Contact: {contact!r}")
            return

        user, contact_ip, contact_port = parsed

        if not self._validate_ip(contact_ip, expected_src_ip):
            self._dbg(f"  -> IP mismatch: {contact_ip} vs {expected_src_ip}")
            return

        if not (1 <= contact_port <= 65535):
            self._dbg(f"  -> port out of range: {contact_port}")
            return

        # ── strict-mode extras ──────────────────────────────────────
        if self.strict:
            if not self._strict_validate(headers, expected_src_ip, method):
                return

        # ── create expectation (firewall pinhole) ───────────────────
        exp = {
            'segment_index': seg_idx,
            'method': method,
            'contact_ip': contact_ip,
            'contact_port': contact_port,
            'user': user,
        }
        self.expectations.append(exp)
        self._dbg(f"  -> PINHOLE CREATED: {contact_ip}:{contact_port}")

    # ── helpers ─────────────────────────────────────────────────────

    def _match_method(self, text):
        """Case-insensitive match of a SIP method at text[0]."""
        upper = text[:12].upper()
        for m in sorted(self._ALL_METHODS, key=len, reverse=True):
            if upper.startswith(m):
                if len(text) > len(m) and text[len(m)] == ' ':
                    return m
        return None

    def _validate_request_line(self, line, method):
        """Validate: METHOD sip:<domain>[;params] SIP/2.0"""
        parts = line.split(' ', 2)
        if len(parts) < 3:
            return False
        if parts[0].upper() != method:
            return False
        if not parts[1].lower().startswith('sip:'):
            return False
        if not parts[2].strip().startswith('SIP/2.0'):
            return False
        return True

    def _parse_headers(self, header_text):
        """Parse SIP headers into {lowercase_key: value}."""
        headers = {}
        current_key = None
        for line in header_text.split('\r\n'):
            if not line:
                continue
            if line[0] in (' ', '\t') and current_key:
                headers[current_key] += ' ' + line.strip()
                continue
            colon = line.find(':')
            if colon > 0:
                current_key = line[:colon].strip().lower()
                headers[current_key] = line[colon + 1:].strip()
        return headers

    def _parse_contact(self, value):
        """
        Parse Contact: <sip:user@IP:port[;params]>

        Returns (user, ip, port) or None.
        """
        m = re.match(
            r'<sip:([^@]+)@(\d{1,3}(?:\.\d{1,3}){3}):(\d{1,5})(?:;[^>]*)?>',
            value,
        )
        if not m:
            return None
        return m.group(1), m.group(2), int(m.group(3))

    def _validate_ip(self, contact_ip, expected_ip):
        """
        Validate Contact IP matches expected source IP.
        Rejects octets with leading zeros (e.g. '01' for 1).
        """
        try:
            c = contact_ip.split('.')
            e = expected_ip.split('.')
            if len(c) != 4 or len(e) != 4:
                return False
            for co, eo in zip(c, e):
                if int(co) != int(eo):
                    return False
                if co != str(int(co)):
                    return False
            return True
        except (ValueError, IndexError):
            return False

    def _strict_validate(self, headers, expected_ip, method):
        """Additional checks for strict-mode ALGs."""
        # Via
        via = headers.get('via')
        if not via:
            self._dbg("  -> strict: missing Via")
            return False
        if not re.match(r'SIP/2\.0/(TCP|UDP)\s+\S+', via):
            self._dbg("  -> strict: invalid Via format")
            return False
        if expected_ip not in via:
            self._dbg("  -> strict: Via IP mismatch")
            return False

        # Call-ID
        if 'call-id' not in headers:
            self._dbg("  -> strict: missing Call-ID")
            return False

        # CSeq (must reference the same method)
        cseq = headers.get('cseq')
        if not cseq:
            self._dbg("  -> strict: missing CSeq")
            return False
        parts = cseq.strip().split()
        if len(parts) < 2 or parts[1].upper() != method:
            self._dbg("  -> strict: CSeq method mismatch")
            return False

        # Expires > 0  (Expires: 0 means de-register per RFC 3261)
        expires = headers.get('expires')
        if expires is None:
            self._dbg("  -> strict: missing Expires")
            return False
        try:
            if int(expires.strip()) <= 0:
                self._dbg("  -> strict: Expires <= 0")
                return False
        except ValueError:
            self._dbg("  -> strict: non-integer Expires")
            return False

        # Max-Forwards
        if 'max-forwards' not in headers:
            self._dbg("  -> strict: missing Max-Forwards")
            return False

        return True

    # ── debug ───────────────────────────────────────────────────────

    def _dbg(self, msg):
        if self.debug:
            self._log.append(msg)
            print(f"[ALG] {msg}", file=sys.stderr)

    def get_log(self):
        return list(self._log)
