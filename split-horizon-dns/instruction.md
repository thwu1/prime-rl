A BIND9 split-horizon DNS deployment for `infra.example.com` is broken. The configuration at `/etc/bind/named.conf` and zone files under `/etc/bind/zones/` contain multiple interacting errors that prevent the service from starting.

The authoritative host inventory is at `/app/hosts.csv` and service record definitions at `/app/services.csv`. The repaired deployment must satisfy all of the following:

- BIND9 running and answering queries on port 8053
- Clean `named-checkconf` and `named-checkzone` validation for every zone
- Correct split-horizon resolution: internal view for RFC 1918 and localhost clients, external view for all others
- All record types resolving correctly (A, AAAA, MX, CNAME, SRV, TXT, PTR) in both views
- Forward and reverse DNS (IPv4 and IPv6) consistent with the CSV inventory
- Zone transfers restricted; recursion available only to internal clients