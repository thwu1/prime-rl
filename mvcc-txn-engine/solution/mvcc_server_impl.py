"""Unix domain socket server for the MVCC key-value store — Reference Implementation."""


import os
import signal
import socket
import sys
import threading

sys.path.insert(0, "/app")
from mvcc_store import MVCCStore, ConflictError


def handle_client(conn, store):
    txn = None
    buf = b""
    try:
        while True:
            data = conn.recv(4096)
            if not data:
                break
            buf += data
            quit_flag = False
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode("utf-8").strip()
                if not text:
                    continue
                parts = text.split(None, 2)
                cmd = parts[0].upper()

                try:
                    if cmd == "QUIT":
                        quit_flag = True
                        break
                    elif cmd == "BEGIN":
                        if txn is not None:
                            conn.sendall(b"ERROR already in transaction\n")
                        else:
                            txn = store.new_txn()
                            conn.sendall(b"OK\n")
                    elif cmd == "GET":
                        if txn is None:
                            conn.sendall(b"ERROR no active transaction\n")
                        else:
                            key = parts[1]
                            val = txn.get(key)
                            if val is None:
                                conn.sendall(b"NONE\n")
                            else:
                                conn.sendall(f"VALUE {val}\n".encode())
                    elif cmd == "PUT":
                        if txn is None:
                            conn.sendall(b"ERROR no active transaction\n")
                        else:
                            key = parts[1]
                            value = parts[2] if len(parts) > 2 else ""
                            txn.put(key, value)
                            conn.sendall(b"OK\n")
                    elif cmd == "DELETE":
                        if txn is None:
                            conn.sendall(b"ERROR no active transaction\n")
                        else:
                            key = parts[1]
                            txn.delete(key)
                            conn.sendall(b"OK\n")
                    elif cmd == "SCAN":
                        if txn is None:
                            conn.sendall(b"ERROR no active transaction\n")
                        else:
                            start_key = parts[1]
                            end_key = parts[2] if len(parts) > 2 else ""
                            results = txn.scan(start_key, end_key)
                            for k, v in results:
                                conn.sendall(f"ITEM {k} {v}\n".encode())
                            conn.sendall(b"END\n")
                    elif cmd == "COMMIT":
                        if txn is None:
                            conn.sendall(b"ERROR no active transaction\n")
                        else:
                            try:
                                ts = txn.commit()
                                conn.sendall(f"COMMITTED {ts}\n".encode())
                            except ConflictError as e:
                                conn.sendall(f"CONFLICT {e}\n".encode())
                            txn = None
                    elif cmd == "ROLLBACK":
                        if txn is None:
                            conn.sendall(b"ERROR no active transaction\n")
                        else:
                            txn.rollback()
                            txn = None
                            conn.sendall(b"OK\n")
                    elif cmd == "GC":
                        removed = store.gc()
                        conn.sendall(f"REMOVED {removed}\n".encode())
                    else:
                        conn.sendall(f"ERROR unknown command: {cmd}\n".encode())
                except Exception as e:
                    conn.sendall(f"ERROR {e}\n".encode())
                    if cmd == "COMMIT":
                        txn = None
            if quit_flag:
                break
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        if txn is not None:
            try:
                txn.rollback()
            except Exception:
                pass
        conn.close()


def main():
    if len(sys.argv) < 3:
        print(
            "Usage: mvcc_server.py <socket_path> <db_path> [--serializable]",
            file=sys.stderr,
        )
        sys.exit(1)

    sock_path = sys.argv[1]
    db_path = sys.argv[2]
    serializable = "--serializable" in sys.argv

    store = MVCCStore(db_path, serializable=serializable)

    if os.path.exists(sock_path):
        os.unlink(sock_path)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    server.listen(16)

    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

    try:
        while True:
            conn, _ = server.accept()
            t = threading.Thread(target=handle_client, args=(conn, store), daemon=True)
            t.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        server.close()
        store.close()
        try:
            os.unlink(sock_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
