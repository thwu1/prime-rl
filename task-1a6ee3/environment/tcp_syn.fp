; p0f TCP SYN signature database (subset)
; Format: label = class_type:os_class:os_name
;         sig   = ver:ittl:olen:mss:wsize,scale:olayout:quirks:pclass
;
; Fields:
;   ver       - IP version (4 or 6), * = any
;   ittl      - initial TTL (after guessing from observed)
;   olen      - IP options length
;   mss       - maximum segment size, * = any
;   wsize     - window size: absolute, mss*N, or mtu*N
;   scale     - window scale shift count, -1 if absent
;   olayout   - ordered TCP option list (mss,nop,ws,sok,sack,ts,eol+N)
;   quirks    - comma-separated flags: df,id+,id-,ecn,0+,seq-,ack+,ack-,
;               uptr+,urgf,pushf,ts1-,ts2+,opt+,exws,bad
;   pclass    - payload class: 0=no payload, 1=payload, *=any
;
; Quirk definitions:
;   df    - DF (Don't Fragment) flag set in IP header
;   id+   - non-zero IP ID when DF is set
;   id-   - zero IP ID when DF is NOT set
;   ecn   - ECN bits set in IP ToS field (tos & 0x03 != 0)
;   0+    - "must be zero" bit set in IP flags
;   seq-  - sequence number is zero
;   ack+  - non-zero ACK number when ACK flag is NOT set
;   ack-  - zero ACK number when ACK flag IS set
;   uptr+ - non-zero urgent pointer when URG flag is NOT set
;   urgf  - URG flag set
;   pushf - PSH flag set
;   ts1-  - timestamp value (ts_val) is zero
;   ts2+  - timestamp echo reply (ts_ecr) is non-zero in SYN
;   opt+  - non-zero padding after EOL option
;   exws  - window scale > 14
;   bad   - malformed TCP option (wrong length field)

[tcp:request]

label = s:linux:5.x
sig   = *:64:0:*:mss*20,7:mss,sok,ts,nop,ws:df,id+:0

label = s:linux:4.x:ecn
sig   = *:64:0:*:mss*20,7:mss,sok,ts,nop,ws:df,id+,ecn:0

label = s:win:10
sig   = *:128:0:*:8192,8:mss,nop,ws,nop,nop,sok:df,id+:0

label = s:osx:12.x
sig   = *:64:0:*:65535,6:mss,nop,ws,nop,nop,ts,sok,eol+1:df,id+:0

label = s:freebsd:13.x
sig   = *:64:0:*:65535,6:mss,nop,ws,sok,ts:df:0

label = s:win:server2019
sig   = *:128:0:*:8192,8:mss,nop,ws,sok,ts:df,id+:0

label = s:openbsd:7.x
sig   = *:64:0:*:16384,0:mss,nop,nop,sok,nop,ws,nop,nop,ts:df:0

label = s:solaris:11
sig   = *:255:0:*:mss*34,0:nop,nop,ts,mss,nop,ws,sok,eol+1::0
