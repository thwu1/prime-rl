#!/usr/bin/env python3
"""
Client library for the Redis-like binary protocol server.

Protocol format:
  Request:  [4-byte msg_len][4-byte nstr][4-byte len1][str1]...[4-byte lenN][strN]
  Response: [4-byte msg_len][serialized_value]

Serialized value tags:
  TAG_NIL (0): just the tag byte
  TAG_ERR (1): tag + 4-byte code + 4-byte strlen + string
  TAG_STR (2): tag + 4-byte len + data
  TAG_INT (3): tag + 8-byte int64 (little-endian)
  TAG_DBL (4): tag + 8-byte double (little-endian)
  TAG_ARR (5): tag + 4-byte count, then count serialized items

Usage:
  from client import RedisClient
  c = RedisClient()
  c.send_command('set', 'mykey', 'myvalue')
  print(c.send_command('get', 'mykey'))   # 'myvalue'
  c.send_command('zadd', 'myzset', '1.5', 'alice')
  print(c.send_command('zscore', 'myzset', 'alice'))  # 1.5
  c.close()
"""

import socket
import struct


class RedisClient:
    def __init__(self, host='127.0.0.1', port=1234):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((host, port))
        self.sock.settimeout(5.0)

    def close(self):
        self.sock.close()

    def send_command(self, *args):
        """Send a command (list of string arguments) and return the parsed response."""
        # Build request body: nstr, then for each string: len + data
        body = struct.pack('<I', len(args))
        for arg in args:
            s = str(arg).encode() if not isinstance(arg, bytes) else arg
            body += struct.pack('<I', len(s)) + s
        # Prefix with total message length
        msg = struct.pack('<I', len(body)) + body
        self.sock.sendall(msg)
        return self._read_response()

    def _read_exact(self, n):
        data = b''
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Connection closed")
            data += chunk
        return data

    def _read_response(self):
        header = self._read_exact(4)
        length = struct.unpack('<I', header)[0]
        data = self._read_exact(length)
        result, _ = self._parse(data, 0)
        return result

    def _parse(self, data, offset):
        tag = data[offset]
        offset += 1
        if tag == 0:  # NIL
            return None, offset
        elif tag == 1:  # ERR
            code = struct.unpack_from('<I', data, offset)[0]
            offset += 4
            slen = struct.unpack_from('<I', data, offset)[0]
            offset += 4
            msg = data[offset:offset + slen].decode()
            offset += slen
            return ('ERR', code, msg), offset
        elif tag == 2:  # STR
            slen = struct.unpack_from('<I', data, offset)[0]
            offset += 4
            s = data[offset:offset + slen].decode()
            offset += slen
            return s, offset
        elif tag == 3:  # INT
            val = struct.unpack_from('<q', data, offset)[0]
            offset += 8
            return val, offset
        elif tag == 4:  # DBL
            val = struct.unpack_from('<d', data, offset)[0]
            offset += 8
            return val, offset
        elif tag == 5:  # ARR
            n = struct.unpack_from('<I', data, offset)[0]
            offset += 4
            items = []
            for _ in range(n):
                item, offset = self._parse(data, offset)
                items.append(item)
            return items, offset
        else:
            raise ValueError(f"Unknown tag: {tag}")


if __name__ == '__main__':
    import sys
    c = RedisClient()
    result = c.send_command(*sys.argv[1:])
    print(result)
    c.close()
