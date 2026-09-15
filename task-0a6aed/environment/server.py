"""
RESP2 protocol server stub for sorted set operations.


Provided: TCP listener, connection handler, RESP2 parser, response serializer.
TODO: Implement command_dispatch() to map Redis commands to BPTreeSortedSet
      operations with correct argument parsing and response formatting.
"""

import socket
import sys
import threading

sys.path.insert(0, "/app")


# ═══════════════════════════════════════════════════════════════════════════════
# RESP2 wire-format helpers
# ═══════════════════════════════════════════════════════════════════════════════


class RESPParser:
    """Reads RESP2 messages from a socket stream."""

    def __init__(self, sock):
        self._file = sock.makefile("rb")

    def read_command(self):
        """Read one command.  Returns list[str] or None on disconnect."""
        try:
            line = self._file.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                return None

            if line.startswith(b"*"):
                count = int(line[1:])
                if count < 0:
                    return None
                args = []
                for _ in range(count):
                    header = self._file.readline().strip()
                    if header.startswith(b"$"):
                        length = int(header[1:])
                        if length < 0:
                            args.append(None)
                        else:
                            data = self._file.read(length + 2)[:length]
                            args.append(data.decode("utf-8", errors="replace"))
                    else:
                        args.append(header.decode("utf-8", errors="replace"))
                return args
            else:
                # Inline command
                parts = line.decode("utf-8", errors="replace").split()
                return parts if parts else None
        except (ConnectionError, OSError, ValueError):
            return None

    def close(self):
        try:
            self._file.close()
        except Exception:
            pass


# ── Response builders ─────────────────────────────────────────────────────────


def resp_ok():
    """Simple string +OK."""
    return b"+OK\r\n"


def resp_pong():
    """Simple string +PONG."""
    return b"+PONG\r\n"


def resp_error(msg):
    """Error response."""
    return f"-ERR {msg}\r\n".encode()


def resp_integer(n):
    """Integer response."""
    return f":{n}\r\n".encode()


def resp_bulk(s):
    """Bulk string response (pass None for null bulk string)."""
    if s is None:
        return b"$-1\r\n"
    encoded = str(s).encode()
    return b"$" + str(len(encoded)).encode() + b"\r\n" + encoded + b"\r\n"


def resp_array(items):
    """Array response.  *items* is a list of already-encoded RESP byte strings."""
    if items is None:
        return b"*-1\r\n"
    return b"*" + str(len(items)).encode() + b"\r\n" + b"".join(items)


def resp_empty_array():
    """Empty array *0."""
    return b"*0\r\n"


# ═══════════════════════════════════════════════════════════════════════════════
# Server
# ═══════════════════════════════════════════════════════════════════════════════


class SortedSetServer:
    """Multi-key sorted set server speaking RESP2 on a configurable TCP port."""

    def __init__(self, host="0.0.0.0", port=6380):
        self.host = host
        self.port = port
        self.stores = {}  # key_name -> BPTreeSortedSet instance
        self._lock = threading.Lock()
        self._running = False

    def _get_store(self, key):
        """Return the BPTreeSortedSet for *key*, creating one if needed."""
        with self._lock:
            if key not in self.stores:
                from sorted_set import BPTreeSortedSet

                self.stores[key] = BPTreeSortedSet()
            return self.stores[key]

    def _delete_store(self, key):
        """Delete the sorted set for *key*.  Returns True if it existed."""
        with self._lock:
            return self.stores.pop(key, None) is not None

    # ── TODO ──────────────────────────────────────────────────────────────────

    def command_dispatch(self, args):
        """Map a parsed RESP command to sorted set operations.

        Parameters
        ----------
        args : list[str]
            Command and arguments, e.g. ``["ZADD", "mykey", "1.0", "alpha"]``.
            The first element is the command name (case-insensitive).

        Returns
        -------
        bytes
            RESP2-encoded response to send to the client.

        Use the ``resp_*`` helper functions defined above to build responses.
        Use ``_get_store(key)`` / ``_delete_store(key)`` to manage per-key
        sorted set instances.
        """
        raise NotImplementedError("command dispatch not yet implemented")

    # ── Connection handling (provided) ────────────────────────────────────────

    def _handle_client(self, conn, addr):
        parser = RESPParser(conn)
        try:
            while self._running:
                args = parser.read_command()
                if args is None:
                    break
                try:
                    response = self.command_dispatch(args)
                    conn.sendall(response)
                except NotImplementedError:
                    conn.sendall(resp_error("command dispatch not implemented"))
                except Exception as exc:
                    conn.sendall(resp_error(str(exc)))
        except (ConnectionError, BrokenPipeError, OSError):
            pass
        finally:
            parser.close()
            conn.close()

    def run(self):
        """Start accepting connections.  Blocks until ``stop()`` is called."""
        self._running = True
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(128)
        self._sock.settimeout(1.0)

        print(
            f"Sorted-set server listening on {self.host}:{self.port}", flush=True
        )

        while self._running:
            try:
                conn, addr = self._sock.accept()
                t = threading.Thread(
                    target=self._handle_client,
                    args=(conn, addr),
                    daemon=True,
                )
                t.start()
            except socket.timeout:
                continue
            except OSError:
                break

        self._sock.close()

    def stop(self):
        self._running = False


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 6380
    server = SortedSetServer(port=port)
    try:
        server.run()
    except KeyboardInterrupt:
        server.stop()
