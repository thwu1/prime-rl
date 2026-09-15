
import os
import re
import subprocess
import tempfile

import pytest

INCLUDE_PATH = "/app/include"
COMPILE_CMD = "g++ -std=c++20 -O2 -I {} -lpthread".format(INCLUDE_PATH)


def _compile_and_run(source: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Write *source* to a temp file, compile, run, and return the result."""
    with tempfile.NamedTemporaryFile(
        suffix=".cpp", mode="w", delete=False, dir="/tmp"
    ) as f:
        f.write(source)
        src = f.name
    binary = src.replace(".cpp", "")
    try:
        comp = subprocess.run(
            "{} -o {} {}".format(COMPILE_CMD, binary, src),
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if comp.returncode != 0:
            return comp
        return subprocess.run(
            binary, capture_output=True, text=True, timeout=timeout
        )
    finally:
        for p in (src, binary):
            try:
                os.unlink(p)
            except FileNotFoundError:
                pass


# -- Cache-line alignment ----------------------------------------------------


class TestCacheLineAlignment:
    def test_write_read_pos_separation(self):
        """write_pos_ and read_pos_ must be >= 64 bytes apart (separate cache lines)."""
        r = _compile_and_run(
            r"""
#include "spsc_queue.h"
#include <cstdint>
#include <cstdio>
int main() {
    spsc::QueueHeader h;
    auto w = reinterpret_cast<uintptr_t>(&h.write_pos_);
    auto rd = reinterpret_cast<uintptr_t>(&h.read_pos_);
    auto diff = (rd > w) ? (rd - w) : (w - rd);
    printf("DIFF=%lu\n", (unsigned long)diff);
    return (diff >= 64) ? 0 : 1;
}
"""
        )
        assert r.returncode == 0, (
            "write_pos_ and read_pos_ must be on separate cache lines.\n"
            + r.stdout
            + r.stderr
        )


# -- Memory ordering ---------------------------------------------------------


class TestMemoryOrdering:
    def _read_queue_source(self) -> str:
        with open(os.path.join(INCLUDE_PATH, "spsc_queue.h")) as f:
            return f.read()

    def test_no_seq_cst(self):
        src = self._read_queue_source()
        n = src.count("memory_order_seq_cst")
        assert n == 0, "Found {} uses of memory_order_seq_cst (expected 0)".format(n)

    def test_has_release(self):
        src = self._read_queue_source()
        assert "memory_order_release" in src, "Missing memory_order_release in producer"

    def test_has_acquire(self):
        src = self._read_queue_source()
        assert "memory_order_acquire" in src, "Missing memory_order_acquire in consumer"


# -- Single-threaded correctness ---------------------------------------------


class TestSingleThreadedCorrectness:
    def test_variable_length_messages(self):
        """Messages of various sizes must round-trip correctly."""
        r = _compile_and_run(
            r"""
#include "spsc_queue.h"
#include <cstdio>
#include <cstdint>
#include <cstring>
int main() {
    const size_t cap = 1 << 20;
    auto* hdr = new spsc::QueueHeader();
    auto* buf = new char[cap]();
    spsc::Producer prod(hdr, buf, cap);
    spsc::Consumer cons(hdr, buf, cap);

    uint32_t sizes[] = {1, 4, 7, 33, 64, 100, 255, 1000, 4096};
    const int N = sizeof(sizes) / sizeof(sizes[0]);

    for (int s = 0; s < N; s++) {
        uint8_t msg[4096];
        for (uint32_t i = 0; i < sizes[s]; i++)
            msg[i] = (uint8_t)((i * 37 + s * 13) & 0xFF);
        if (!prod.write(msg, sizes[s])) {
            printf("FAIL:write:%d\n", s);
            return 1;
        }
    }
    prod.flush();

    for (int s = 0; s < N; s++) {
        uint8_t out[4096];
        uint32_t got = cons.read(out, sizeof(out));
        if (got != sizes[s]) {
            printf("FAIL:size:%d:exp=%u:got=%u\n", s, sizes[s], got);
            return 1;
        }
        for (uint32_t i = 0; i < got; i++) {
            uint8_t exp = (uint8_t)((i * 37 + s * 13) & 0xFF);
            if (out[i] != exp) {
                printf("FAIL:data:%d:%u\n", s, i);
                return 1;
            }
        }
    }

    uint8_t tmp[16];
    if (cons.read(tmp, sizeof(tmp)) != 0) {
        printf("FAIL:extra\n");
        return 1;
    }
    printf("PASS\n");
    delete[] buf;
    delete hdr;
    return 0;
}
"""
        )
        assert r.returncode == 0, "Variable-length round-trip failed:\n" + r.stdout + r.stderr
        assert "PASS" in r.stdout


# -- Wraparound handling ----------------------------------------------------


class TestWraparound:
    def test_no_buffer_overflow(self):
        """Producer must not write past the buffer boundary."""
        r = _compile_and_run(
            r"""
#include "spsc_queue.h"
#include <cstdio>
#include <cstdint>
#include <cstring>
int main() {
    const size_t cap = 1024;
    const size_t guard = 128;
    auto* buffer = new char[cap + guard];
    std::memset(buffer + cap, 0xDE, guard);

    auto* hdr = new spsc::QueueHeader();
    spsc::Producer prod(hdr, buffer, cap);

    // Each message: 90 payload + 4 prefix = 94 total.
    // 10 messages => 940 bytes consumed, offset = 940.
    uint8_t data[90];
    std::memset(data, 0xAB, sizeof(data));
    for (int i = 0; i < 10; i++) {
        if (!prod.write(data, 90)) { printf("FAIL:fill:%d\n", i); return 1; }
    }
    // Next message: 100 payload + 4 = 104 total.  940 + 104 = 1044 > 1024 => wraps.
    uint8_t big[100];
    std::memset(big, 0xCD, sizeof(big));
    if (!prod.write(big, 100)) { printf("FAIL:wrap_write\n"); return 1; }
    prod.flush();

    for (size_t i = 0; i < guard; i++) {
        if ((uint8_t)buffer[cap + i] != 0xDE) {
            printf("FAIL:overflow:%zu\n", i);
            delete[] buffer; delete hdr;
            return 1;
        }
    }
    printf("PASS\n");
    delete[] buffer; delete hdr;
    return 0;
}
"""
        )
        assert r.returncode == 0, "Buffer overflow detected:\n" + r.stdout + r.stderr
        assert "PASS" in r.stdout

    def test_wraparound_data_integrity(self):
        """A message straddling the buffer boundary must survive a round-trip."""
        r = _compile_and_run(
            r"""
#include "spsc_queue.h"
#include <cstdio>
#include <cstdint>
#include <cstring>
int main() {
    const size_t cap = 1024;
    const size_t extra = 256;
    auto* buffer = new char[cap + extra]();
    auto* hdr = new spsc::QueueHeader();
    spsc::Producer prod(hdr, buffer, cap);
    spsc::Consumer cons(hdr, buffer, cap);

    // Fill 10 * 94 = 940 bytes.
    uint8_t filler[90];
    std::memset(filler, 0x42, sizeof(filler));
    for (int i = 0; i < 10; i++) {
        filler[0] = (uint8_t)i;
        prod.write(filler, 90);
    }
    prod.flush();
    uint8_t sink[256];
    for (int i = 0; i < 10; i++) {
        if (cons.read(sink, sizeof(sink)) != 90) {
            printf("FAIL:fill_read:%d\n", i);
            return 1;
        }
    }

    // Offset = 940.  Write 100-byte payload => total 104, wraps at 1024.
    uint8_t wrap_data[100];
    for (int i = 0; i < 100; i++) wrap_data[i] = (uint8_t)(i ^ 0xA5);
    prod.write(wrap_data, 100);
    prod.flush();

    // Poison the guard zone AFTER write, BEFORE read.
    std::memset(buffer + cap, 0xFF, extra);

    uint8_t out[256];
    uint32_t sz = cons.read(out, sizeof(out));
    if (sz != 100) { printf("FAIL:wrap_sz:%u\n", sz); return 1; }
    for (int i = 0; i < 100; i++) {
        uint8_t exp = (uint8_t)(i ^ 0xA5);
        if (out[i] != exp) {
            printf("FAIL:wrap_data[%d]:got=0x%02X:exp=0x%02X\n", i, out[i], exp);
            return 1;
        }
    }

    printf("PASS\n");
    delete[] buffer; delete hdr;
    return 0;
}
"""
        )
        assert r.returncode == 0, "Wraparound data integrity failed:\n" + r.stdout + r.stderr
        assert "PASS" in r.stdout


# -- Write reservation -------------------------------------------------------


class TestWriteReservation:
    def test_deferred_publication(self):
        """Consumer must NOT see all messages before flush (proves reservation works)."""
        r = _compile_and_run(
            r"""
#include "spsc_queue.h"
#include <cstdio>
#include <cstdint>
int main() {
    const size_t cap = 1 << 20;
    auto* hdr = new spsc::QueueHeader();
    auto* buf = new char[cap]();
    spsc::Producer prod(hdr, buf, cap);
    spsc::Consumer cons(hdr, buf, cap);

    const int N = 700;
    uint8_t msg[100];
    for (int i = 0; i < N; i++) {
        for (int j = 0; j < 100; j++) msg[j] = (uint8_t)(i + j);
        prod.write(msg, 100);
    }
    // DO NOT flush yet.

    int visible = 0;
    uint8_t tmp[256];
    while (cons.read(tmp, sizeof(tmp)) > 0) visible++;

    if (visible >= N) {
        printf("FAIL:no_reservation:visible=%d\n", visible);
        delete[] buf; delete hdr;
        return 1;
    }

    prod.flush();
    while (cons.read(tmp, sizeof(tmp)) > 0) visible++;

    if (visible != N) {
        printf("FAIL:after_flush:visible=%d:expected=%d\n", visible, N);
        delete[] buf; delete hdr;
        return 1;
    }

    printf("PASS:visible_before_flush=%d\n", visible - (N - visible));
    delete[] buf; delete hdr;
    return 0;
}
"""
        )
        assert r.returncode == 0, "Write reservation test failed:\n" + r.stdout + r.stderr
        assert "PASS" in r.stdout


# -- Concurrent correctness -------------------------------------------------


class TestConcurrentCorrectness:
    def test_producer_consumer_threads(self):
        """50 000 messages exchanged between two threads must arrive in order."""
        r = _compile_and_run(
            r"""
#include "spsc_queue.h"
#include <atomic>
#include <cstdio>
#include <cstdint>
#include <thread>
int main() {
    const size_t cap = 1 << 20;
    auto* hdr = new spsc::QueueHeader();
    auto* buf = new char[cap]();
    spsc::Producer prod(hdr, buf, cap);
    spsc::Consumer cons(hdr, buf, cap);

    const int N = 50000;
    std::atomic<bool> done{false};

    auto producer = std::thread([&]() {
        for (int i = 0; i < N; i++) {
            uint32_t val = (uint32_t)i;
            prod.write(&val, sizeof(val));
            if (i % 1000 == 999) prod.flush();
        }
        prod.flush();
        done.store(true, std::memory_order_release);
    });

    int received = 0;
    uint32_t v;
    int spins = 0;
    while (received < N) {
        uint32_t sz = cons.read(&v, sizeof(v));
        if (sz == sizeof(uint32_t)) {
            if (v != (uint32_t)received) {
                printf("FAIL:order:%d:got=%u\n", received, v);
                producer.join();
                delete[] buf; delete hdr;
                return 1;
            }
            received++;
            spins = 0;
        } else {
            spins++;
            if (spins > 200000000 && done.load(std::memory_order_acquire)) {
                printf("FAIL:stuck:%d/%d\n", received, N);
                producer.join();
                delete[] buf; delete hdr;
                return 1;
            }
        }
    }
    producer.join();
    printf("PASS:%d\n", received);
    delete[] buf; delete hdr;
    return 0;
}
""",
            timeout=60,
        )
        assert r.returncode == 0, "Concurrent test failed:\n" + r.stdout + r.stderr
        assert "PASS" in r.stdout


# -- Protocol header ---------------------------------------------------------


class TestProtocol:
    def test_header_initialization(self):
        """ShmManager::create() must set magic, version, and queue descriptor."""
        r = _compile_and_run(
            r"""
#include "shm_protocol.h"
#include <cstdio>
int main() {
    const char* path = "/tmp/_proto_init_test.dat";
    size_t cap = 4096;
    void* ptr = spsc::ShmManager::create(path, cap);
    auto* h = spsc::ShmManager::get_header(ptr);
    int ok = 1;
    if (h->magic != spsc::kProtocolMagic) {
        printf("FAIL:magic=0x%X\n", h->magic); ok = 0;
    }
    if (h->major_version != spsc::kMajorVersion) {
        printf("FAIL:major=%u\n", h->major_version); ok = 0;
    }
    if (h->minor_version != spsc::kMinorVersion) {
        printf("FAIL:minor=%u\n", h->minor_version); ok = 0;
    }
    if (h->queue_offset == 0 || h->queue_offset > 1024) {
        printf("FAIL:offset=%lu\n", (unsigned long)h->queue_offset); ok = 0;
    }
    if (h->queue_capacity != cap) {
        printf("FAIL:capacity=%lu\n", (unsigned long)h->queue_capacity); ok = 0;
    }
    spsc::ShmManager::destroy(path, ptr, sizeof(spsc::ProtocolHeader) + cap);
    if (ok) printf("PASS\n");
    return ok ? 0 : 1;
}
"""
        )
        assert r.returncode == 0, "Header init failed:\n" + r.stdout + r.stderr
        assert "PASS" in r.stdout

    def test_magic_validation(self):
        """open() must reject a corrupted magic number."""
        r = _compile_and_run(
            r"""
#include "shm_protocol.h"
#include <cstdio>
int main() {
    const char* path = "/tmp/_proto_magic_test.dat";
    size_t cap = 4096;
    void* ptr = spsc::ShmManager::create(path, cap);
    spsc::ShmManager::get_header(ptr)->magic = 0xDEADBEEF;
    bool caught = false;
    try { spsc::ShmManager::open(path); }
    catch (...) { caught = true; }
    spsc::ShmManager::destroy(path, ptr, sizeof(spsc::ProtocolHeader) + cap);
    printf(caught ? "PASS\n" : "FAIL:magic_not_validated\n");
    return caught ? 0 : 1;
}
"""
        )
        assert r.returncode == 0, "Magic validation failed:\n" + r.stdout + r.stderr
        assert "PASS" in r.stdout

    def test_version_validation(self):
        """open() must reject an incompatible major version."""
        r = _compile_and_run(
            r"""
#include "shm_protocol.h"
#include <cstdio>
int main() {
    const char* path = "/tmp/_proto_ver_test.dat";
    size_t cap = 4096;
    void* ptr = spsc::ShmManager::create(path, cap);
    spsc::ShmManager::get_header(ptr)->major_version = 99;
    bool caught = false;
    try { spsc::ShmManager::open(path); }
    catch (...) { caught = true; }
    spsc::ShmManager::destroy(path, ptr, sizeof(spsc::ProtocolHeader) + cap);
    printf(caught ? "PASS\n" : "FAIL:version_not_validated\n");
    return caught ? 0 : 1;
}
"""
        )
        assert r.returncode == 0, "Version validation failed:\n" + r.stdout + r.stderr
        assert "PASS" in r.stdout


# -- Stress test (end-to-end) -----------------------------------------------


class TestStressTest:
    def test_make_stress_passes(self):
        """The production readiness stress test must pass after all fixes."""
        r = subprocess.run(
            "cd /app && make stress",
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert r.returncode == 0, "make stress failed:\n" + r.stdout + r.stderr


# -- Analysis report ---------------------------------------------------------


class TestAnalysisReport:
    def test_report_exists(self):
        """A diagnostic analysis report must be present at /app/analysis.md."""
        assert os.path.isfile("/app/analysis.md"), "/app/analysis.md not found"

    def test_report_substantive(self):
        """The report must contain substantive analysis, not a stub."""
        with open("/app/analysis.md") as f:
            content = f.read()
        assert len(content) >= 800, (
            "analysis.md too brief ({} bytes, minimum 800)".format(len(content))
        )

    def test_report_covers_multiple_issues(self):
        """The report must document multiple distinct defects with separate sections."""
        with open("/app/analysis.md") as f:
            content = f.read()
        headings = re.findall(r"^#{1,4}\s+\S", content, re.MULTILINE)
        assert len(headings) >= 4, (
            "analysis.md needs >= 4 headed sections to cover all defects "
            "(found {})".format(len(headings))
        )
