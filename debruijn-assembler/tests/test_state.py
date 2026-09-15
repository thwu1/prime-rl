
import subprocess
import os
import shutil
import random
import pytest

ASSEMBLER = "/app/assembler"


def run_assembler(binary, input_file, timeout=120):
    """Run the assembler and return sorted output lines."""
    result = subprocess.run(
        [binary, input_file],
        capture_output=True, text=True, timeout=timeout
    )
    assert result.returncode == 0, (
        f"Assembler exited with code {result.returncode}: {result.stderr[:500]}"
    )
    lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
    return sorted(lines)


def build_and_traverse(kmers_file):
    """Independent Python de Bruijn graph assembly for verification."""
    with open(kmers_file) as f:
        k = int(f.readline().strip())
        n = int(f.readline().strip())

        graph = {}
        start_nodes = []

        for _ in range(n):
            parts = f.readline().strip().split('\t')
            kmer, fwd, bwd = parts[0], parts[1], parts[2]
            graph[kmer] = (fwd, bwd)
            if bwd == 'F':
                start_nodes.append((kmer, fwd))

    contigs = []
    for start_kmer, start_fwd in start_nodes:
        contig = start_kmer
        cur_fwd = start_fwd
        while cur_fwd != 'F':
            contig += cur_fwd
            next_kmer = contig[-k:]
            if next_kmer not in graph:
                break
            cur_fwd = graph[next_kmer][0]
        contigs.append(contig)

    return sorted(contigs)


def generate_dataset(k, num_contigs, min_len, max_len, seed, output_file):
    """Generate a synthetic k-mer dataset (self-contained, independent of /app/generate_data.py)."""
    rng = random.Random(seed)

    seen_kmers = set()
    valid_contigs = []
    attempts = 0

    while len(valid_contigs) < num_contigs and attempts < num_contigs * 10:
        attempts += 1
        length = rng.randint(min_len, max_len)
        contig = ''.join(rng.choice('ACGT') for _ in range(length))

        if length < k:
            continue

        contig_kmers = []
        valid = True
        for i in range(length - k + 1):
            kmer = contig[i:i + k]
            if kmer in seen_kmers:
                valid = False
                break
            contig_kmers.append(kmer)

        if not valid or len(set(contig_kmers)) != len(contig_kmers):
            continue

        seen_kmers.update(contig_kmers)
        valid_contigs.append(contig)

    all_kmers = {}
    for contig in valid_contigs:
        clen = len(contig)
        for i in range(clen - k + 1):
            kmer = contig[i:i + k]
            fwd = contig[i + k] if i + k < clen else 'F'
            bwd = contig[i - 1] if i > 0 else 'F'
            all_kmers[kmer] = (fwd, bwd)

    with open(output_file, 'w') as f:
        f.write(f"{k}\n")
        f.write(f"{len(all_kmers)}\n")
        for kmer, (fwd, bwd) in all_kmers.items():
            f.write(f"{kmer}\t{fwd}\t{bwd}\n")

    return len(all_kmers)


class TestAssembler:
    """Test suite for the de Bruijn graph genome assembler."""

    def test_cmake_build(self):
        """Verify CMakeLists.txt exists and cmake produces a valid build."""
        assert os.path.isfile("/app/CMakeLists.txt"), (
            "CMakeLists.txt not found in /app/"
        )
        build_dir = "/tmp/cmake_verify_build"
        shutil.rmtree(build_dir, ignore_errors=True)
        os.makedirs(build_dir)

        r = subprocess.run(
            ["cmake", "-S", "/app", "-B", build_dir],
            capture_output=True, text=True, timeout=60
        )
        assert r.returncode == 0, f"cmake configure failed:\n{r.stderr}"

        r = subprocess.run(
            ["cmake", "--build", build_dir],
            capture_output=True, text=True, timeout=120
        )
        assert r.returncode == 0, f"cmake build failed:\n{r.stderr}"

        # Verify cmake produced an executable named 'assembler'
        binary_found = False
        for root, dirs, files in os.walk(build_dir):
            for fname in files:
                path = os.path.join(root, fname)
                if fname == "assembler" and os.access(path, os.X_OK):
                    binary_found = True
                    break
            if binary_found:
                break
        assert binary_found, (
            "cmake build did not produce an 'assembler' executable"
        )

    def test_small_correctness(self):
        """Verify correct contigs on the small hand-crafted dataset (k=3, 3 contigs)."""
        output = run_assembler(ASSEMBLER, "/app/data/small.kmers")
        expected = build_and_traverse("/app/data/small.kmers")
        # Cross-check with reference file
        with open("/app/data/small.contigs") as f:
            ref = sorted([l.strip() for l in f if l.strip()])
        assert expected == ref, (
            f"Python verifier disagrees with reference: {expected} vs {ref}"
        )
        assert output == expected, (
            f"Assembler output differs:\nExpected: {expected}\nGot: {output}"
        )

    def test_medium_correctness(self):
        """Verify correct assembly on a medium dataset (k=19, ~10K k-mers)."""
        kmers_file = "/tmp/test_medium.kmers"
        n = generate_dataset(
            k=19, num_contigs=100, min_len=80, max_len=200,
            seed=42, output_file=kmers_file
        )
        assert n > 5000, f"Dataset too small: {n} k-mers"

        output = run_assembler(ASSEMBLER, kmers_file)
        expected = build_and_traverse(kmers_file)
        assert output == expected, (
            f"Assembler output differs on medium dataset ({n} k-mers). "
            f"Got {len(output)} contigs, expected {len(expected)}"
        )

    def test_valgrind_memcheck(self):
        """Verify zero memory errors and zero definite leaks via Valgrind memcheck."""
        kmers_file = "/tmp/test_memcheck.kmers"
        generate_dataset(
            k=19, num_contigs=50, min_len=60, max_len=150,
            seed=77, output_file=kmers_file
        )
        result = subprocess.run(
            ["valgrind", "--tool=memcheck", "--leak-check=full",
             "--errors-for-leak-kinds=definite",
             "--error-exitcode=42",
             ASSEMBLER, kmers_file],
            capture_output=True, text=True, timeout=120
        )
        assert result.returncode != 42, (
            f"Valgrind memcheck detected errors:\n{result.stderr[-1500:]}"
        )
        assert result.returncode == 0, (
            f"Assembler failed under Valgrind: exit code {result.returncode}\n"
            f"{result.stderr[-500:]}"
        )
        # Verify ERROR SUMMARY shows 0 errors
        for line in result.stderr.split('\n'):
            if 'ERROR SUMMARY' in line:
                parts = line.split(':')
                if len(parts) >= 2:
                    count_str = parts[-1].strip().split()[0]
                    errors = int(count_str.replace(',', ''))
                    assert errors == 0, (
                        f"Valgrind memcheck found {errors} error(s)"
                    )
                break

    def test_valgrind_massif_memory(self):
        """Verify peak heap < 40 MB on ~800K k-mers (k=31) via Valgrind massif."""
        kmers_file = "/tmp/test_massif.kmers"
        n = generate_dataset(
            k=31, num_contigs=7000, min_len=100, max_len=200,
            seed=456, output_file=kmers_file
        )
        assert n > 600000, f"Dataset too small for memory test: {n} k-mers"

        massif_out = "/tmp/massif.out"
        result = subprocess.run(
            ["valgrind", "--tool=massif", "--pages-as-heap=no",
             "--massif-out-file=" + massif_out,
             ASSEMBLER, kmers_file],
            capture_output=True, text=True, timeout=240
        )
        assert result.returncode == 0, (
            f"Assembler failed under massif: {result.stderr[-500:]}"
        )

        # Verify correctness of output produced under massif
        output_lines = sorted(
            [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
        )
        expected = build_and_traverse(kmers_file)
        assert output_lines == expected, (
            f"Assembler output differs under massif. "
            f"Got {len(output_lines)} contigs, expected {len(expected)}"
        )

        # Parse massif output file for peak heap bytes
        peak_bytes = 0
        assert os.path.isfile(massif_out), "Massif output file not created"
        with open(massif_out) as f:
            for line in f:
                line = line.strip()
                if line.startswith('mem_heap_B='):
                    val = int(line.split('=')[1])
                    peak_bytes = max(peak_bytes, val)

        assert peak_bytes > 0, (
            "Could not parse heap usage from massif output"
        )
        peak_mb = peak_bytes / (1024 * 1024)
        assert peak_mb < 40, (
            f"Peak heap {peak_mb:.1f} MB exceeds 40 MB limit"
        )

    def test_single_kmer_contigs(self):
        """Test edge case: contigs that are exactly k bases long."""
        tmpf = "/tmp/test_single.kmers"
        with open(tmpf, 'w') as f:
            f.write("5\n")
            f.write("3\n")
            f.write("ACGTG\tF\tF\n")
            f.write("TTTAA\tC\tF\n")
            f.write("TTAAC\tF\tT\n")

        output = run_assembler(ASSEMBLER, tmpf)
        expected = build_and_traverse(tmpf)
        assert output == expected, (
            f"Single-kmer contig test failed:\nExpected: {expected}\nGot: {output}"
        )

    def test_long_contig(self):
        """Test with a single very long contig (~10K bases)."""
        kmers_file = "/tmp/test_long.kmers"
        n = generate_dataset(
            k=19, num_contigs=1, min_len=10000, max_len=10000,
            seed=999, output_file=kmers_file
        )
        assert n > 9000, f"Long contig dataset too small: {n} k-mers"

        output = run_assembler(ASSEMBLER, kmers_file)
        expected = build_and_traverse(kmers_file)
        assert output == expected, "Long contig assembly failed"
