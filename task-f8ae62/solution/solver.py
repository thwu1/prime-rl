#!/usr/bin/env python3
"""
Solution: C2 Redirector Hardening and Detection Engineering

Reads profile specifications, generates correct Apache VirtualHost config,
writes YARA rules, and classifies HTTP traffic.
"""


import os
import json
import struct
import configparser
import re


# ===================================================================
# Part 1: Fix Apache VirtualHost Configuration
# ===================================================================

def read_profiles(profiles_dir='/app/profiles'):
    """Parse all .profile files (INI format)."""
    profiles = {}
    for fn in sorted(os.listdir(profiles_dir)):
        if not fn.endswith('.profile'):
            continue
        name = fn.replace('.profile', '')
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.read(os.path.join(profiles_dir, fn))
        profiles[name] = cfg
    return profiles


def escape_for_regex(s):
    """Escape a literal string for use in Apache mod_rewrite PCRE regex."""
    out = []
    for ch in s:
        if ch in r'\.()[]{}*+?^$|':
            out.append('\\')
        out.append(ch)
    return ''.join(out)


def query_format_to_regex(fmt):
    """Convert profile query_format to PCRE regex.
    E.g. 'id={hex8}&token={hex16}' -> '^id=[a-f0-9]{8}&token=[a-f0-9]{16}$'
    """
    def replace_placeholder(m):
        ptype = m.group(1)
        if ptype.startswith('hex'):
            n = ptype[3:]
            return '[a-f0-9]{' + n + '}'
        elif ptype.startswith('digit'):
            n = ptype[5:]
            return '[0-9]{' + n + '}'
        elif ptype.startswith('alphanum'):
            n = ptype[8:]
            return '[a-zA-Z0-9]{' + n + '}'
        elif ptype.startswith('alpha'):
            n = ptype[5:]
            return '[a-z]{' + n + '}'
        elif ptype.startswith('base64_'):
            parts = ptype[7:].split('_')
            return '[A-Za-z0-9+/=]{' + parts[0] + ',' + parts[1] + '}'
        elif ptype == 'uuid':
            return '[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}'
        return m.group(0)

    pattern = re.sub(r'\{(\w+)\}', replace_placeholder, fmt)
    return '^' + pattern + '$'


def cookie_format_to_regex(fmt):
    """Convert profile cookie format to PCRE regex.
    E.g. 'session={base64_16_64}' -> 'session=[A-Za-z0-9+/=]{16,64}'
    """
    def replace_placeholder(m):
        ptype = m.group(1)
        if ptype.startswith('hex'):
            n = ptype[3:]
            return '[a-f0-9]{' + n + '}'
        elif ptype.startswith('alphanum'):
            n = ptype[8:]
            return '[a-zA-Z0-9]{' + n + '}'
        elif ptype.startswith('alpha'):
            n = ptype[5:]
            return '[a-z]{' + n + '}'
        elif ptype.startswith('base64_'):
            parts = ptype[7:].split('_')
            return '[A-Za-z0-9+/=]{' + parts[0] + ',' + parts[1] + '}'
        return m.group(0)

    return re.sub(r'\{(\w+)\}', replace_placeholder, fmt)


def build_vhost_config(profiles):
    """Generate correct Apache VirtualHost config from profile specs."""
    lines = [
        '<VirtualHost *:80>',
        '    ServerName localhost',
        '    DocumentRoot /app/apache/htdocs',
        '',
        '    <Directory /app/apache/htdocs>',
        '        AllowOverride None',
        '        Require all granted',
        '    </Directory>',
        '',
        '    ProxyRequests Off',
        '',
        '    RewriteEngine On',
        '',
    ]

    for name in sorted(profiles.keys()):
        cfg = profiles[name]
        ua = cfg.get('user-agent', 'value')
        ua_re = escape_for_regex(ua)
        get_uri = cfg.get('http-get', 'uri')
        post_uri = cfg.get('http-post', 'uri')
        query_fmt = cfg.get('http-get', 'query_format', fallback='')
        cookie_fmt = cfg.get('cookie', 'format', fallback='')

        get_uri_re = escape_for_regex(get_uri)
        post_uri_re = escape_for_regex(post_uri)

        # --- GET rule ---
        lines.append('    # {} profile - GET'.format(name))
        lines.append('    RewriteCond %{{HTTP_USER_AGENT}} "^{}$"'.format(ua_re))
        if query_fmt:
            qregex = query_format_to_regex(query_fmt)
            lines.append('    RewriteCond %{{QUERY_STRING}} "{}"'.format(qregex))
        if cookie_fmt:
            cregex = cookie_format_to_regex(cookie_fmt)
            lines.append('    RewriteCond %{{HTTP_COOKIE}} "{}"'.format(cregex))
        # Check required custom headers
        if cfg.has_section('headers'):
            for hdr_name, hdr_val in cfg.items('headers'):
                canonical = '-'.join(w.capitalize() for w in hdr_name.split('-'))
                lines.append('    RewriteCond %{{HTTP:{}}} !^$'.format(canonical))
        lines.append('    RewriteRule ^{}$ http://127.0.0.1:50050{} [P,L,QSA]'.format(
            get_uri_re, get_uri))
        lines.append('')

        # --- POST rule ---
        lines.append('    # {} profile - POST'.format(name))
        lines.append('    RewriteCond %{REQUEST_METHOD} POST')
        lines.append('    RewriteCond %{{HTTP_USER_AGENT}} "^{}$"'.format(ua_re))
        if cookie_fmt:
            cregex = cookie_format_to_regex(cookie_fmt)
            lines.append('    RewriteCond %{{HTTP_COOKIE}} "{}"'.format(cregex))
        if cfg.has_section('headers'):
            for hdr_name, hdr_val in cfg.items('headers'):
                canonical = '-'.join(w.capitalize() for w in hdr_name.split('-'))
                lines.append('    RewriteCond %{{HTTP:{}}} !^$'.format(canonical))
        lines.append('    RewriteRule ^{}$ http://127.0.0.1:50050{} [P,L]'.format(
            post_uri_re, post_uri))
        lines.append('')

    # Catch-all redirect
    lines.append('    # Default - redirect non-matching traffic to decoy')
    lines.append('    RewriteRule ^/(.*)$ https://www.example.com/$1 [R=302,L]')
    lines.append('')
    lines.append('    ErrorLog ${APACHE_LOG_DIR}/error.log')
    lines.append('    CustomLog ${APACHE_LOG_DIR}/access.log combined')
    lines.append('</VirtualHost>')

    return '\n'.join(lines) + '\n'


# ===================================================================
# Part 2: YARA Detection Rules
# ===================================================================

def analyze_payload(filepath):
    """Extract implant ID (wide string at 0x300), XOR key (0x500),
    and encoded shellcode (0x501..0x511) from a PE payload."""
    with open(filepath, 'rb') as f:
        data = f.read()

    assert data[0:2] == b'MZ', "{}: not a PE binary".format(filepath)

    # Decode wide string at offset 0x300
    wide_region = data[0x300:0x380]
    chars = []
    i = 0
    while i < len(wide_region) - 1:
        lo, hi = wide_region[i], wide_region[i + 1]
        if hi == 0 and 0x20 <= lo <= 0x7e:
            chars.append(chr(lo))
            i += 2
        else:
            break
    implant_id = ''.join(chars)

    # XOR key at 0x500
    xor_key = data[0x500]

    # Encoded shellcode: 16 bytes at 0x501
    encoded_sc = data[0x501:0x511]

    return implant_id, xor_key, encoded_sc


def write_yara_rule(profile_name, implant_id, encoded_sc_bytes):
    """Generate a YARA rule detecting the given payload indicators."""
    hex_str = ' '.join('{:02x}'.format(b) for b in encoded_sc_bytes)
    return '''rule {name}_beacon {{
    meta:
        description = "Detects {name} C2 beacon payload"
        author = "Detection Engineer"
        profile = "{name}"
    strings:
        $implant_id = "{iid}" wide
        $xor_shellcode = {{ {hexs} }}
    condition:
        uint16(0) == 0x5A4D and all of them
}}
'''.format(name=profile_name, iid=implant_id, hexs=hex_str)


# ===================================================================
# Part 3: Traffic Classification
# ===================================================================

def classify_traffic(traffic, profiles):
    """Classify source IPs from the traffic log against profile specs."""

    matchers = {}
    c2_uris = set()
    for name, cfg in profiles.items():
        get_uri = cfg.get('http-get', 'uri', fallback='')
        post_uri = cfg.get('http-post', 'uri', fallback='')
        ua = cfg.get('user-agent', 'value', fallback='')
        cookie_fmt = cfg.get('cookie', 'format', fallback='')
        cookie_prefix = cookie_fmt.split('=')[0] + '=' if '=' in cookie_fmt else ''
        matchers[name] = {
            'ua': ua,
            'get_uri': get_uri,
            'post_uri': post_uri,
            'cookie_prefix': cookie_prefix,
        }
        c2_uris.add(get_uri)
        c2_uris.add(post_uri)

    ip_entries = {}
    for entry in traffic:
        ip_entries.setdefault(entry['src_ip'], []).append(entry)

    c2_hosts = {}
    analyst_ips = []

    for ip, entries in ip_entries.items():
        profile_votes = {}
        for entry in entries:
            uri_path = entry['uri'].split('?')[0]
            for name, m in matchers.items():
                if entry.get('user_agent', '') != m['ua']:
                    continue
                if uri_path not in (m['get_uri'], m['post_uri']):
                    continue
                if m['cookie_prefix'] and m['cookie_prefix'] not in entry.get('cookie', ''):
                    continue
                profile_votes[name] = profile_votes.get(name, 0) + 1

        if profile_votes:
            best = max(profile_votes, key=profile_votes.get)
            c2_hosts[ip] = best
        else:
            accessed_c2 = any(
                e['uri'].split('?')[0] in c2_uris for e in entries
            )
            if accessed_c2:
                analyst_ips.append(ip)

    total_c2 = sum(len(ip_entries[ip]) for ip in c2_hosts)

    return c2_hosts, total_c2, sorted(analyst_ips)


# ===================================================================
# Main
# ===================================================================

def main():
    profiles = read_profiles()

    # --- Part 1: Fix Apache VirtualHost config ---
    vhost = build_vhost_config(profiles)
    with open('/etc/apache2/sites-available/000-default.conf', 'w') as f:
        f.write(vhost)
    print("[+] Fixed /etc/apache2/sites-available/000-default.conf")

    # --- Part 2: YARA rules ---
    os.makedirs('/app/detection', exist_ok=True)
    sample_map = {
        'payload_001.bin': 'alpha',
        'payload_002.bin': 'bravo',
        'payload_003.bin': 'charlie',
    }
    for sample, profile in sample_map.items():
        path = '/app/samples/{}'.format(sample)
        implant_id, xor_key, encoded_sc = analyze_payload(path)
        rule = write_yara_rule(profile, implant_id, encoded_sc)
        rule_path = '/app/detection/{}.yar'.format(profile)
        with open(rule_path, 'w') as f:
            f.write(rule)
        print("[+] Wrote {} (implant={}, key=0x{:02x})".format(
            rule_path, implant_id, xor_key))

    # --- Part 3: Traffic analysis ---
    with open('/app/traffic/access.log') as f:
        traffic = json.load(f)

    c2_hosts, total_c2, analyst_ips = classify_traffic(traffic, profiles)

    os.makedirs('/app/analysis', exist_ok=True)
    result = {
        'c2_hosts': c2_hosts,
        'total_c2_requests': total_c2,
        'analyst_ips': analyst_ips,
    }
    with open('/app/analysis/c2_sessions.json', 'w') as f:
        json.dump(result, f, indent=2)
    print("[+] Wrote /app/analysis/c2_sessions.json")
    print("    C2 hosts: {}".format(c2_hosts))
    print("    Total C2 requests: {}".format(total_c2))
    print("    Analyst IPs: {}".format(analyst_ips))


if __name__ == '__main__':
    main()
