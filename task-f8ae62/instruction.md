A C2 redirector environment is staged in `/app/`. Three C2 beacon profiles with specifications in `/app/profiles/` (INI format) operate through an Apache reverse proxy, but the VirtualHost configuration at `/etc/apache2/sites-available/000-default.conf` is broken — legitimate C2 traffic is being exposed, analyst probes reach the teamserver, POST URIs are unhandled, and one profile has no rules at all.

Produce three deliverables:

**Functioning redirector.** Fix the Apache configuration so that HTTP requests matching a profile's full specification are proxied to the teamserver at `http://127.0.0.1:50050`, and all non-matching traffic receives a 302 redirect to `https://www.example.com`. Both GET and POST URIs for every profile must be handled. A request that matches a C2 URI but fails other profile criteria must not reach the teamserver. Apache modules `rewrite`, `proxy`, and `proxy_http` are already enabled. Restart Apache after applying changes.

**Per-profile YARA detection rules.** Binary samples in `/app/samples/` — each `payload_*.bin` corresponds to one profile. Analyze the binaries and write YARA rules to `/app/detection/alpha.yar`, `/app/detection/bravo.yar`, and `/app/detection/charlie.yar` that detect only the corresponding payload. No false positives on `clean_*.bin` files or other profiles' payloads.

**Traffic classification report.** The log at `/app/traffic/access.log` (JSON array) contains mixed browsing, C2 callbacks, and analyst probes. Cross-reference against the profile specifications and write `/app/analysis/c2_sessions.json`:

```json
{
  "c2_hosts": {"<ip>": "<profile_name>", ...},
  "total_c2_requests": <int>,
  "analyst_ips": ["<ip>", ...]
}
```

`c2_hosts` maps each compromised source IP to its profile name. `total_c2_requests` is the total HTTP request count from all C2 hosts. `analyst_ips` lists IPs that probed C2 URIs without fully matching any profile specification.