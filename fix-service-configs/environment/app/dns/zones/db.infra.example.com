$TTL 86400
@   IN  SOA ns1.infra.example.com. admin.infra.example.com. (
            2024010101  ; serial
            3600        ; refresh
            900         ; retry
            604800      ; expire
            86400       ; minimum TTL
)

; Nameservers
        IN  NS  ns1.infra.example.com
        IN  NS  ns2.infra.example.com

; Mail
        IN  MX  10 mail.infra.example.com.

; Zone apex - redirect to load balancer
@       IN  CNAME lb.infra.example.com.

; Host records
ns1     IN  A   10.20.30.2
ns2     IN  A   10.20.30.3
web1    IN  A   10.20.30.10
web2    IN  A   203.0.113.10
api1    IN  A   10.20.30.15
db1     IN  A   10.20.30.20
mail    IN  A   10.20.30.25
