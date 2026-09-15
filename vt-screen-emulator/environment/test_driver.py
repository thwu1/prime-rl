#!/usr/bin/env python3
"""
PTY-based test driver for VT-420 terminal escape sequence protocol server.

Launches vt_server.py as a subprocess connected via PTY in raw mode,
provides methods to send escape sequences and read DECRQCRA checksum
responses via DCS protocol.

Based on the communication patterns from esctest2 (Thomas Dickey / George Nachman).
"""

import os
import pty
import select
import signal
import sys
import termios
import time

ESC = "\x1b"
CSI = ESC + "["
DCS = ESC + "P"
ST = ESC + "\\"


class ProtocolError(Exception):
    """Raised when the DCS response cannot be parsed."""
    pass


class VTSession:
    """
    Manages a PTY-connected VT-420 server process.

    Creates a pseudo-terminal pair, sets raw mode on the slave to prevent
    any terminal line-discipline processing, then forks and execs the
    server.  The master side is used for sending escape sequences and
    reading DCS responses.
    """

    def __init__(self, server_path="/app/vt_server.py", cols=80, rows=24):
        self.cols = cols
        self.rows = rows
        self._pid_counter = 1

        # Create PTY pair
        self.master_fd, slave_fd = pty.openpty()

        # Set raw mode on slave -- disable ALL terminal processing
        try:
            attrs = termios.tcgetattr(slave_fd)
            attrs[0] = 0                          # iflag: no input processing
            attrs[1] = 0                          # oflag: no output processing
            attrs[3] = 0                          # lflag: no echo, no canonical
            attrs[6][termios.VMIN] = 1            # read returns after 1 byte
            attrs[6][termios.VTIME] = 0           # no inter-byte timeout
            termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)
        except termios.error:
            pass

        pid = os.fork()
        if pid == 0:
            # ------- child (becomes the VT server) -------
            os.close(self.master_fd)
            os.setsid()
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            if slave_fd > 2:
                os.close(slave_fd)
            os.execvp(
                sys.executable,
                [sys.executable, server_path, str(cols), str(rows)],
            )
            os._exit(1)
        else:
            # ------- parent (test driver) -------
            self.pid = pid
            os.close(slave_fd)
            # Also set raw on master to avoid kernel mangling
            try:
                old = termios.tcgetattr(self.master_fd)
                old[0] = 0
                old[1] = 0
                old[3] = 0
                old[6][termios.VMIN] = 1
                old[6][termios.VTIME] = 0
                termios.tcsetattr(self.master_fd, termios.TCSANOW, old)
            except termios.error:
                pass
            time.sleep(0.5)  # let server initialise

    # ------------------------------------------------------------------ I/O
    def _send(self, data):
        if isinstance(data, str):
            data = data.encode("latin-1")
        os.write(self.master_fd, data)
        time.sleep(0.03)

    def _read_until(self, terminator, timeout=5.0):
        """Read from master until *terminator* (str) appears or timeout."""
        term_bytes = terminator.encode("latin-1")
        buf = b""
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = max(0.01, deadline - time.time())
            r, _, _ = select.select([self.master_fd], [], [], remaining)
            if r:
                chunk = os.read(self.master_fd, 4096)
                if not chunk:
                    break
                buf += chunk
                if term_bytes in buf:
                    return buf.decode("latin-1", errors="replace")
        return buf.decode("latin-1", errors="replace")

    def _flush_input(self):
        """Discard any pending bytes on the master side."""
        while True:
            r, _, _ = select.select([self.master_fd], [], [], 0.05)
            if not r:
                break
            os.read(self.master_fd, 4096)

    # -------------------------------------------------------- VT commands
    def cup(self, row, col):
        """CUP – Cursor Position."""
        self._send(f"{CSI}{row};{col}H")

    def write_text(self, text):
        """Send printable characters."""
        self._send(text)

    def ed(self, mode=2):
        """ED – Erase in Display."""
        self._send(f"{CSI}{mode}J")

    def decstbm(self, top=None, bottom=None):
        """DECSTBM – Set Top and Bottom Margins."""
        if top is None and bottom is None:
            self._send(f"{CSI}r")
        else:
            self._send(f"{CSI}{top};{bottom}r")

    def ind(self):
        """IND – Index (ESC D)."""
        self._send(f"{ESC}D")

    def ri(self):
        """RI – Reverse Index (ESC M)."""
        self._send(f"{ESC}M")

    def deccra(self, src_top, src_left, src_bottom, src_right, src_page,
               dst_top, dst_left, dst_page):
        """DECCRA – Copy Rectangular Area."""
        self._send(
            f"{CSI}{src_top};{src_left};{src_bottom};{src_right};"
            f"{src_page};{dst_top};{dst_left};{dst_page}$v"
        )

    def decfra(self, char_code, top, left, bottom, right):
        """DECFRA – Fill Rectangular Area."""
        self._send(f"{CSI}{char_code};{top};{left};{bottom};{right}$x")

    def decera(self, top, left, bottom, right):
        """DECERA – Erase Rectangular Area."""
        self._send(f"{CSI}{top};{left};{bottom};{right}$z")

    def decset_decom(self):
        """DECSET – Enable Origin Mode (mode 6)."""
        self._send(f"{CSI}?6h")

    def decreset_decom(self):
        """DECRESET – Disable Origin Mode (mode 6)."""
        self._send(f"{CSI}?6l")

    # ------------------------------------------------- DECRQCRA query
    def decrqcra(self, top, left, bottom, right):
        """Send DECRQCRA and return the integer checksum from the DCS reply."""
        pid = self._pid_counter
        self._pid_counter += 1
        self._flush_input()
        self._send(f"{CSI}{pid};0;{top};{left};{bottom};{right}*y")
        response = self._read_until(ST, timeout=5.0)
        return self._parse_dcs(response, pid)

    def _parse_dcs(self, response, expected_pid):
        """Parse ``ESC P <pid> ! ~ <hex> ESC \\`` and return int checksum."""
        dcs_idx = response.find(DCS)
        if dcs_idx == -1:
            raise ProtocolError(f"No DCS found in response: {response!r}")
        st_idx = response.find(ST, dcs_idx + len(DCS))
        if st_idx == -1:
            raise ProtocolError(f"No ST terminator in response: {response!r}")
        body = response[dcs_idx + len(DCS):st_idx]
        marker = "!~"
        mi = body.find(marker)
        if mi == -1:
            raise ProtocolError(f"No '!~' marker in DCS body: {body!r}")
        rpid = int(body[:mi])
        hexval = body[mi + 2:]
        if rpid != expected_pid:
            raise ProtocolError(
                f"PID mismatch: got {rpid}, expected {expected_pid}"
            )
        return int(hexval, 16)

    # -------------------------------------------------------- lifecycle
    def close(self):
        try:
            os.close(self.master_fd)
        except OSError:
            pass
        try:
            os.kill(self.pid, signal.SIGTERM)
        except OSError:
            pass
        try:
            os.waitpid(self.pid, 0)
        except (OSError, ChildProcessError):
            pass
