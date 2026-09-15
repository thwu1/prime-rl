
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <algorithm>
#include <fstream>
#include <iostream>
#include <map>
#include <string>
#include <vector>

#include <arpa/inet.h>
#include <netinet/ip.h>
#include <netinet/tcp.h>
#include <sys/stat.h>

// ---------- Internet checksum (RFC 1071) ----------

static uint16_t compute_checksum(const void* buf, int len) {
    const uint16_t* p = static_cast<const uint16_t*>(buf);
    uint32_t sum = 0;
    while (len > 1) {
        sum += *p++;
        len -= 2;
    }
    if (len == 1) {
        sum += *reinterpret_cast<const uint8_t*>(p);
    }
    while (sum >> 16)
        sum = (sum & 0xFFFF) + (sum >> 16);
    return static_cast<uint16_t>(~sum);
}

static bool verify_ip_checksum(const uint8_t* pkt, int iphdr_len) {
    return compute_checksum(pkt, iphdr_len) == 0;
}

static bool verify_tcp_checksum(const struct iphdr* ip,
                                const uint8_t* tcp_start,
                                int tcp_total_len) {
    int pseudo_len = 12;
    int total = pseudo_len + tcp_total_len;
    int padded = total + (total % 2);
    std::vector<uint8_t> buf(padded, 0);

    // Build pseudo-header
    std::memcpy(&buf[0], &ip->saddr, 4);
    std::memcpy(&buf[4], &ip->daddr, 4);
    buf[8] = 0;
    buf[9] = IPPROTO_TCP;
    uint16_t tcp_len_net = htons(static_cast<uint16_t>(tcp_total_len));
    std::memcpy(&buf[10], &tcp_len_net, 2);

    // TCP segment (header + options + payload)
    std::memcpy(&buf[12], tcp_start, tcp_total_len);

    return compute_checksum(buf.data(), padded) == 0;
}

// ---------- Data structures ----------

struct ConnKey {
    uint32_t ip1, ip2;
    uint16_t port1, port2;

    static ConnKey make(uint32_t sip, uint16_t sport,
                        uint32_t dip, uint16_t dport) {
        ConnKey k;
        if (sip < dip || (sip == dip && sport <= dport)) {
            k.ip1 = sip;  k.port1 = sport;
            k.ip2 = dip;  k.port2 = dport;
        } else {
            k.ip1 = dip;  k.port1 = dport;
            k.ip2 = sip;  k.port2 = sport;
        }
        return k;
    }

    bool operator<(const ConnKey& o) const {
        if (ip1 != o.ip1) return ip1 < o.ip1;
        if (port1 != o.port1) return port1 < o.port1;
        if (ip2 != o.ip2) return ip2 < o.ip2;
        return port2 < o.port2;
    }
};

struct Segment {
    uint32_t seq;
    std::vector<uint8_t> data;
};

struct HalfStream {
    uint32_t isn = 0;
    bool isn_set = false;
    std::vector<Segment> segments;
};

enum ConnState {
    CS_SYN_SENT,
    CS_SYN_RCVD,
    CS_ESTABLISHED,
    CS_FIN_WAIT,
    CS_CLOSED,
    CS_RESET
};

struct Connection {
    uint32_t client_ip = 0;
    uint16_t client_port = 0;
    uint32_t server_ip = 0;
    uint16_t server_port = 0;
    int index = 0;

    HalfStream fwd;  // client -> server
    HalfStream rev;  // server -> client

    ConnState state = CS_SYN_SENT;
    bool has_client_fin = false;
    bool has_server_fin = false;
};

static const char* state_str(ConnState s) {
    switch (s) {
        case CS_SYN_SENT:    return "SYN_SENT";
        case CS_SYN_RCVD:    return "SYN_RCVD";
        case CS_ESTABLISHED: return "ESTABLISHED";
        case CS_FIN_WAIT:    return "FIN_WAIT";
        case CS_CLOSED:      return "CLOSED";
        case CS_RESET:       return "RESET";
    }
    return "UNKNOWN";
}

// ---------- Reassembly with wraparound and injection detection ----------

static std::vector<uint8_t> reassemble_stream(HalfStream& hs,
                                               int& retrans,
                                               int& injections) {
    if (!hs.isn_set || hs.segments.empty())
        return {};

    // Base = ISN+1 (SYN consumes one sequence number)
    // All offsets computed relative to base using unsigned subtraction,
    // which handles 32-bit wraparound correctly via modular arithmetic.
    uint32_t base = hs.isn + 1;

    // Sort segments by offset from base. Using stable_sort to preserve
    // arrival order for segments with identical sequence numbers (needed
    // for deterministic first-data-wins policy on retransmissions).
    std::stable_sort(hs.segments.begin(), hs.segments.end(),
                     [base](const Segment& a, const Segment& b) {
                         return (a.seq - base) < (b.seq - base);
                     });

    std::vector<uint8_t> result;
    uint32_t assembled = 0;  // offset past base of next byte to assemble

    for (auto& seg : hs.segments) {
        if (seg.data.empty()) continue;

        uint32_t seg_start = seg.seq - base;
        uint32_t seg_len = static_cast<uint32_t>(seg.data.size());
        uint32_t seg_end = seg_start + seg_len;

        if (seg_end <= assembled) {
            // Entire segment already covered by assembled data.
            // Check if payload matches (retransmission) or differs (injection).
            bool mismatch = false;
            for (size_t i = 0; i < seg.data.size(); i++) {
                if (seg_start + i < result.size() &&
                    result[seg_start + i] != seg.data[i]) {
                    mismatch = true;
                    break;
                }
            }
            if (mismatch)
                injections++;
            else
                retrans++;
            continue;
        }

        if (seg_start < assembled) {
            // Partial overlap with assembled data.
            uint32_t overlap_len = assembled - seg_start;
            // Check overlapping portion for byte mismatch (injection).
            bool mismatch = false;
            for (uint32_t i = 0; i < overlap_len; i++) {
                if (seg_start + i < result.size() &&
                    result[seg_start + i] != seg.data[i]) {
                    mismatch = true;
                    break;
                }
            }
            if (mismatch)
                injections++;
            // Append only the non-overlapping tail.
            result.insert(result.end(),
                          seg.data.begin() + overlap_len, seg.data.end());
            assembled = seg_end;
        } else if (seg_start == assembled) {
            // Contiguous: append entire segment.
            result.insert(result.end(), seg.data.begin(), seg.data.end());
            assembled = seg_end;
        } else {
            // Gap: fill with zeros, then append segment.
            uint32_t gap = seg_start - assembled;
            result.resize(result.size() + gap, 0);
            result.insert(result.end(), seg.data.begin(), seg.data.end());
            assembled = seg_end;
        }
    }

    return result;
}

// ---------- Main ----------

int main(int argc, char* argv[]) {
    if (argc != 3) {
        std::fprintf(stderr, "Usage: %s <capture_file> <output_dir>\n",
                     argv[0]);
        return 1;
    }

    const char* capture_path = argv[1];
    const char* output_dir   = argv[2];

    std::ifstream fin(capture_path, std::ios::binary);
    if (!fin) {
        std::fprintf(stderr, "Cannot open %s\n", capture_path);
        return 1;
    }

    mkdir(output_dir, 0755);

    std::map<ConnKey, Connection> connections;
    std::vector<ConnKey> conn_order;
    int checksum_errors = 0;

    // Read and process packets
    while (fin) {
        uint32_t pkt_len_net;
        if (!fin.read(reinterpret_cast<char*>(&pkt_len_net), 4))
            break;
        uint32_t pkt_len = ntohl(pkt_len_net);
        if (pkt_len == 0 || pkt_len > 65535) break;

        std::vector<uint8_t> pkt(pkt_len);
        if (!fin.read(reinterpret_cast<char*>(pkt.data()), pkt_len))
            break;

        // --- Parse IPv4 header ---
        if (pkt_len < 20) continue;
        const struct iphdr* ip =
            reinterpret_cast<const struct iphdr*>(pkt.data());
        if (ip->version != 4) continue;

        int iphdr_len = ip->ihl * 4;
        if (iphdr_len < 20 || static_cast<uint32_t>(iphdr_len) > pkt_len)
            continue;
        if (ntohs(ip->tot_len) != pkt_len) continue;
        if (ip->protocol != IPPROTO_TCP) continue;

        if (!verify_ip_checksum(pkt.data(), iphdr_len)) {
            checksum_errors++;
            continue;
        }

        // --- Parse TCP header (variable length via data offset) ---
        const uint8_t* tcp_start = pkt.data() + iphdr_len;
        int tcp_total_len = pkt_len - iphdr_len;
        if (tcp_total_len < 20) continue;

        const struct tcphdr* tcp =
            reinterpret_cast<const struct tcphdr*>(tcp_start);
        int tcphdr_len = tcp->doff * 4;
        if (tcphdr_len < 20 || tcphdr_len > tcp_total_len) continue;

        if (!verify_tcp_checksum(ip, tcp_start, tcp_total_len)) {
            checksum_errors++;
            continue;
        }

        uint32_t sip   = ip->saddr;
        uint32_t dip   = ip->daddr;
        uint16_t sport = ntohs(tcp->source);
        uint16_t dport = ntohs(tcp->dest);
        uint32_t seq   = ntohl(tcp->seq);
        int payload_len = tcp_total_len - tcphdr_len;
        const uint8_t* payload = tcp_start + tcphdr_len;

        ConnKey key = ConnKey::make(sip, sport, dip, dport);

        // --- SYN (new connection) ---
        if (tcp->syn && !tcp->ack) {
            if (connections.find(key) == connections.end()) {
                Connection conn;
                conn.client_ip   = sip;
                conn.client_port = sport;
                conn.server_ip   = dip;
                conn.server_port = dport;
                conn.index       = static_cast<int>(conn_order.size());
                conn.fwd.isn     = seq;
                conn.fwd.isn_set = true;
                conn.state       = CS_SYN_SENT;
                connections[key] = conn;
                conn_order.push_back(key);
            }
            continue;
        }

        auto it = connections.find(key);
        if (it == connections.end()) continue;
        Connection& conn = it->second;

        bool is_fwd = (sip == conn.client_ip && sport == conn.client_port);

        // --- SYN-ACK ---
        if (tcp->syn && tcp->ack) {
            conn.rev.isn     = seq;
            conn.rev.isn_set = true;
            if (conn.state == CS_SYN_SENT)
                conn.state = CS_SYN_RCVD;
            continue;
        }

        // --- RST ---
        if (tcp->rst) {
            conn.state = CS_RESET;
            continue;
        }

        // --- ACK completing handshake ---
        if (conn.state == CS_SYN_RCVD && tcp->ack && !tcp->syn && !tcp->fin) {
            conn.state = CS_ESTABLISHED;
        }

        // --- FIN ---
        if (tcp->fin) {
            if (is_fwd) conn.has_client_fin = true;
            else        conn.has_server_fin = true;

            if (conn.has_client_fin && conn.has_server_fin)
                conn.state = CS_CLOSED;
            else if (conn.state != CS_RESET)
                conn.state = CS_FIN_WAIT;
        }

        // --- Data payload ---
        if (payload_len > 0) {
            if (conn.state == CS_SYN_RCVD)
                conn.state = CS_ESTABLISHED;

            Segment seg;
            seg.seq = seq;
            seg.data.assign(payload, payload + payload_len);

            if (is_fwd)
                conn.fwd.segments.push_back(seg);
            else
                conn.rev.segments.push_back(seg);
        }
    }

    // --- Write output files ---
    for (size_t i = 0; i < conn_order.size(); i++) {
        Connection& conn = connections[conn_order[i]];

        int retrans = 0, injections = 0;
        auto fwd_data = reassemble_stream(conn.fwd, retrans, injections);
        auto rev_data = reassemble_stream(conn.rev, retrans, injections);

        char path[1024];

        // conn_N_fwd.bin
        std::snprintf(path, sizeof(path), "%s/conn_%zu_fwd.bin", output_dir, i);
        {
            std::ofstream out(path, std::ios::binary);
            if (!fwd_data.empty())
                out.write(reinterpret_cast<const char*>(fwd_data.data()),
                          fwd_data.size());
        }

        // conn_N_rev.bin
        std::snprintf(path, sizeof(path), "%s/conn_%zu_rev.bin", output_dir, i);
        {
            std::ofstream out(path, std::ios::binary);
            if (!rev_data.empty())
                out.write(reinterpret_cast<const char*>(rev_data.data()),
                          rev_data.size());
        }

        // conn_N_info.txt
        std::snprintf(path, sizeof(path), "%s/conn_%zu_info.txt",
                      output_dir, i);
        {
            std::ofstream out(path);
            char src_str[INET_ADDRSTRLEN], dst_str[INET_ADDRSTRLEN];
            inet_ntop(AF_INET, &conn.client_ip, src_str, sizeof(src_str));
            inet_ntop(AF_INET, &conn.server_ip, dst_str, sizeof(dst_str));
            out << "SRC=" << src_str << ":" << conn.client_port << "\n";
            out << "DST=" << dst_str << ":" << conn.server_port << "\n";
            out << "FWD_BYTES=" << fwd_data.size() << "\n";
            out << "REV_BYTES=" << rev_data.size() << "\n";
            out << "RETRANSMISSIONS=" << retrans << "\n";
            out << "INJECTIONS=" << injections << "\n";
            out << "STATE=" << state_str(conn.state) << "\n";
        }
    }

    // summary.txt
    {
        char path[1024];
        std::snprintf(path, sizeof(path), "%s/summary.txt", output_dir);
        std::ofstream out(path);
        out << "CONNECTIONS=" << conn_order.size() << "\n";
        out << "CHECKSUM_ERRORS=" << checksum_errors << "\n";
    }

    return 0;
}
