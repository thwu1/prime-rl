"""
Verification tests for the UDP port reuse connection manager.

"""
import json
import os
import subprocess
import time


class TestResultsFile:
    """Verify the results.json output."""

    def test_results_file_exists(self):
        assert os.path.exists('/app/results.json'), \
            "results.json not found — connectx.py must write it"

    def test_minimum_400_connections(self):
        with open('/app/results.json') as f:
            r = json.load(f)
        assert r['total_connections'] >= 400, \
            f"Only {r['total_connections']} connections, need >= 400"

    def test_port_reuse_proven(self):
        """Total connections must exceed the source port pool size."""
        with open('/app/results.json') as f:
            r = json.load(f)
        assert r['total_connections'] > r['port_range_size'], \
            (f"{r['total_connections']} connections <= "
             f"{r['port_range_size']} ports — no port reuse")

    def test_no_overshadowing(self):
        with open('/app/results.json') as f:
            r = json.load(f)
        assert r['duplicates'] == 0, \
            f"{r['duplicates']} duplicate 4-tuples (socket overshadowing)"

    def test_round_trip_success(self):
        with open('/app/results.json') as f:
            r = json.load(f)
        assert r['round_trip_tested'] > 0, "No round-trip tests performed"
        ratio = r['round_trip_successes'] / r['round_trip_tested']
        assert ratio >= 0.9, \
            (f"Only {ratio:.0%} round-trip success "
             f"({r['round_trip_successes']}/{r['round_trip_tested']})")


class TestConnectionsFile:
    """Independently verify connections.txt content."""

    def test_connections_file_exists(self):
        assert os.path.exists('/app/connections.txt'), \
            "connections.txt not found"

    def test_minimum_entries(self):
        with open('/app/connections.txt') as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) >= 400, f"Only {len(lines)} entries"

    def test_all_entries_unique(self):
        with open('/app/connections.txt') as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == len(set(lines)), \
            "Duplicate 4-tuples in connections.txt"

    def test_source_ports_in_range(self):
        with open('/app/connections.txt') as f:
            lines = [l.strip() for l in f if l.strip()]
        for line in lines:
            src, dst = line.split()
            port = int(src.split(':')[1])
            assert 50000 <= port <= 50063, \
                f"Source port {port} outside range 50000-50063"

    def test_source_port_count_limited(self):
        """At most 64 unique source ports used."""
        with open('/app/connections.txt') as f:
            lines = [l.strip() for l in f if l.strip()]
        ports = set()
        for line in lines:
            src, _ = line.split()
            ports.add(int(src.split(':')[1]))
        assert len(ports) <= 64, \
            f"Used {len(ports)} unique source ports, max is 64"

    def test_multiple_destinations(self):
        with open('/app/connections.txt') as f:
            lines = [l.strip() for l in f if l.strip()]
        dsts = set()
        for line in lines:
            _, dst = line.split()
            dsts.add(dst)
        assert len(dsts) >= 8, f"Only {len(dsts)} destinations, need >= 8"

    def test_port_reuse_across_destinations(self):
        """Source ports must be reused across different destinations."""
        with open('/app/connections.txt') as f:
            lines = [l.strip() for l in f if l.strip()]
        port_dests = {}
        for line in lines:
            src, dst = line.split()
            port = int(src.split(':')[1])
            port_dests.setdefault(port, set()).add(dst)

        reused = sum(1 for d in port_dests.values() if len(d) > 1)
        assert reused > 0, "No source port reused across destinations"

        avg = sum(len(d) for d in port_dests.values()) / len(port_dests)
        assert avg > 3, \
            f"Average port reuse factor {avg:.1f}, expected > 3"


class TestExternalConflictDetection:
    """Verify the solution detects sockets from outside its own process."""

    def test_detects_external_4tuple_conflict(self):
        """connect_udp must refuse a 4-tuple already held by another socket."""
        test_code = (
            "import socket, sys, importlib.util\n"
            "holder = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
            "holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
            "holder.bind(('127.0.0.1', 50000))\n"
            "holder.connect(('127.0.0.1', 9001))\n"
            "spec = importlib.util.spec_from_file_location("
            "'connectx', '/app/connectx.py')\n"
            "mod = importlib.util.module_from_spec(spec)\n"
            "try:\n"
            "    spec.loader.exec_module(mod)\n"
            "except SystemExit:\n"
            "    pass\n"
            "fn = getattr(mod, 'connect_udp', None)\n"
            "if fn is None:\n"
            "    print('MISSING_FUNCTION')\n"
            "    sys.exit(1)\n"
            "try:\n"
            "    sd = fn('127.0.0.1', 50000, '127.0.0.1', 9001)\n"
            "    sd.close()\n"
            "    print('NO_CONFLICT')\n"
            "except (OSError, Exception):\n"
            "    print('CONFLICT_DETECTED')\n"
            "holder.close()\n"
        )
        with open('/tmp/_conflict_test.py', 'w') as f:
            f.write(test_code)

        result = subprocess.run(
            ['python3', '/tmp/_conflict_test.py'],
            capture_output=True, text=True, timeout=15
        )

        try:
            os.unlink('/tmp/_conflict_test.py')
        except OSError:
            pass

        stdout = result.stdout.strip()
        assert "MISSING_FUNCTION" not in stdout, \
            "connectx.py must expose connect_udp(src_ip, src_port, dst_ip, dst_port)"
        assert "CONFLICT_DETECTED" in stdout, \
            (f"connect_udp must detect 4-tuple conflicts from existing sockets "
             f"(not just in-process tracking). Got: {stdout}. "
             f"stderr: {result.stderr[:300]}")
