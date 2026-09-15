Implement a TCP stream analysis engine in C++ at `/app/reassemble.cpp` that reads a binary capture file of raw IPv4/TCP packets, reassembles byte streams per connection, and produces per-connection reassembled data files along with metadata.

The specification is at `/app/spec.txt` and a Makefile at `/app/Makefile`.

The program must handle real-world TCP complexities: 32-bit sequence number wraparound where data crosses the unsigned integer boundary, variable-length TCP headers containing options (data offset > 5), out-of-order segment delivery, overlapping segments, and must distinguish between exact retransmissions (identical payload on fully-covered byte range) and conflicting payload injections (differing bytes in overlapping regions). It must verify IPv4 and TCP checksums (skipping and counting invalid packets), and track connection state transitions through the TCP lifecycle (ESTABLISHED, FIN_WAIT, CLOSED, RESET).

Invocation: `/app/reassemble <capture_file> <output_dir>`