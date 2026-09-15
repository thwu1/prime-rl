#!/usr/bin/env python3
"""
Solver for the xenogenetic code recovery task.


Integrates data from gzip-compressed FASTA, XML metadata, tar.gz batch reports,
and SQLite proteomics database to reconstruct training pairs. Discovers the alien
codon table and two context-dependent translation rules, then translates
uncharacterized sequences.
"""

import json
import os
import sqlite3
import xml.etree.ElementTree as ET
from collections import defaultdict


def parse_fasta(path):
    """Parse FASTA file into dict of {gene_id: (dna_sequence, metadata_dict)}."""
    genes = {}
    current_id = None
    current_seq = []
    current_meta = {}

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith('>'):
                if current_id is not None:
                    genes[current_id] = (''.join(current_seq), current_meta)
                parts = line[1:].split()
                current_id = parts[0]
                current_meta = {}
                for p in parts[1:]:
                    if '=' in p:
                        k, v = p.split('=', 1)
                        current_meta[k] = v
                current_seq = []
            else:
                current_seq.append(line)
        if current_id is not None:
            genes[current_id] = (''.join(current_seq), current_meta)

    return genes


def get_valid_runs_from_xml(xml_path):
    """Extract validated run IDs from XML experiment metadata using XPath."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    valid = set()
    for run in root.iter('run'):
        qc = run.find('quality_control')
        if qc is not None:
            qc_passed = qc.find('qc_passed')
            if qc_passed is not None and qc_passed.text.strip().lower() == 'true':
                valid.add(run.get('id'))
    return valid


def get_valid_runs_from_reports(reports_dir):
    """Extract passing batch IDs from extracted batch report JSON files."""
    valid = set()
    for fname in os.listdir(reports_dir):
        if fname.endswith('.json'):
            with open(os.path.join(reports_dir, fname)) as f:
                report = json.load(f)
            if report.get('overall_qc') == 'PASS':
                valid.add(report['batch_id'])
    return valid


def get_proteins(db_path, valid_batches):
    """Query SQLite for highest-confidence proteins from valid-batch characterized genes."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    placeholders = ','.join('?' for _ in valid_batches)
    query = f"""
        SELECT s.gene_id, m.protein_sequence, m.confidence
        FROM samples s
        JOIN mass_spec_results m ON s.gene_id = m.gene_id
        WHERE s.organism = 'xenobiont_alpha'
          AND s.sample_type = 'characterized'
          AND s.batch_id IN ({placeholders})
        ORDER BY s.gene_id, m.confidence DESC
    """

    proteins = {}
    for gene_id, prot, conf in cur.execute(query, list(valid_batches)):
        if gene_id not in proteins:
            proteins[gene_id] = prot

    conn.close()
    return proteins


def get_test_gene_ids(db_path, valid_batches):
    """Get ordered list of uncharacterized xenobiont gene IDs from valid batches."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    placeholders = ','.join('?' for _ in valid_batches)
    query = f"""
        SELECT gene_id FROM samples
        WHERE organism = 'xenobiont_alpha'
          AND sample_type = 'uncharacterized'
          AND batch_id IN ({placeholders})
        ORDER BY gene_id
    """

    ids = [row[0] for row in cur.execute(query, list(valid_batches))]
    conn.close()
    return ids


def get_codons(dna):
    return [dna[i:i+3] for i in range(0, len(dna), 3)]


def btype(prev_last, curr_first):
    if prev_last in 'GC' and curr_first in 'GC':
        return 'gc'
    if prev_last in 'AT' and curr_first in 'AT':
        return 'at'
    return 'mix'


def gc_count(codons):
    return sum(
        1 for i in range(1, len(codons))
        if btype(codons[i-1][-1], codons[i][0]) == 'gc'
    )


def align(codons, protein):
    """Align protein to codons accounting for GC-boundary G insertions."""
    obs = []
    pi = 0
    for i, cdn in enumerate(codons):
        bt = 'none' if i == 0 else btype(codons[i-1][-1], cdn[0])
        if bt == 'gc':
            if pi >= len(protein) or protein[pi] != 'G':
                return None
            pi += 1
        if pi >= len(protein):
            return None
        obs.append((cdn, protein[pi], bt))
        pi += 1
    return obs if pi == len(protein) else None


def translate(codons, table, subs):
    """Translate codons using alien code with context-dependent rules."""
    result = []
    for i, cdn in enumerate(codons):
        aa = table.get(cdn, '?')
        if aa == '*':
            break
        if i > 0:
            bt = btype(codons[i-1][-1], cdn[0])
            if bt == 'gc':
                result.append('G')
            elif bt == 'at' and aa in subs:
                aa = subs[aa]
        result.append(aa)
    return ''.join(result)


def main():
    fasta_path = '/app/data/genome_sequences.fasta'
    db_path = '/app/data/proteomics.db'
    xml_path = '/app/data/experiment_metadata.xml'
    reports_dir = '/tmp/batch_reports'
    out_prot = '/app/results/translated.txt'
    out_table = '/app/results/codon_table.tsv'

    # Step 1: Parse decompressed FASTA
    genes = parse_fasta(fasta_path)
    print(f"FASTA genes: {len(genes)}")

    # Step 2: Get valid runs from XML metadata
    xml_valid = get_valid_runs_from_xml(xml_path)
    print(f"XML valid runs: {sorted(xml_valid)}")

    # Step 3: Get valid runs from batch reports
    report_valid = get_valid_runs_from_reports(reports_dir)
    print(f"Report valid runs: {sorted(report_valid)}")

    # Step 4: Intersect — run must be valid in BOTH sources
    valid_batches = xml_valid & report_valid
    print(f"Cross-validated batches: {sorted(valid_batches)}")

    # Step 5: Query SQLite for proteins and test IDs
    proteins = get_proteins(db_path, valid_batches)
    test_ids = get_test_gene_ids(db_path, valid_batches)
    print(f"Training proteins: {len(proteins)}")
    print(f"Test sequences: {len(test_ids)}")

    # Step 6: Reconstruct training pairs by joining FASTA DNA with SQLite proteins
    training_pairs = []
    for gid in sorted(proteins.keys()):
        if gid in genes:
            dna = genes[gid][0]
            training_pairs.append((dna, proteins[gid]))

    print(f"Training pairs: {len(training_pairs)}")

    # Verify GC insertion rule holds
    for dna, prot in training_pairs:
        cdns = get_codons(dna)
        expected = len(cdns) + gc_count(cdns)
        if expected != len(prot):
            print(f"GC rule mismatch: {dna}")

    # Step 7: Align training data and collect codon observations by boundary type
    clean_obs = defaultdict(lambda: defaultdict(int))
    at_obs = defaultdict(lambda: defaultdict(int))

    for dna, prot in training_pairs:
        cdns = get_codons(dna)
        alignment = align(cdns, prot)
        if alignment is None:
            print(f"Alignment failed: {dna} -> {prot}")
            continue
        for cdn, aa, bt in alignment:
            if bt == 'at':
                at_obs[cdn][aa] += 1
            else:
                clean_obs[cdn][aa] += 1

    # Step 8: Build base codon table from non-AT observations
    table = {}
    for cdn, counts in clean_obs.items():
        table[cdn] = max(counts, key=counts.get)
    print(f"Base table: {len(table)} codons")

    # Step 9: Discover AT-boundary substitution rules
    subs = {}
    sub_evidence = defaultdict(int)
    for cdn, counts in at_obs.items():
        if cdn in table:
            base = table[cdn]
            for aa, n in counts.items():
                if aa != base:
                    sub_evidence[(base, aa)] += n

    for (src, dst), n in sorted(sub_evidence.items(), key=lambda x: -x[1]):
        if src not in subs:
            subs[src] = dst
            print(f"AT substitution: {src} -> {dst} (n={n})")

    # Fill codons only seen at AT boundaries using reverse substitution
    rev_subs = {v: k for k, v in subs.items()}
    for cdn, counts in at_obs.items():
        if cdn not in table:
            aa = max(counts, key=counts.get)
            table[cdn] = rev_subs.get(aa, aa)

    # Mark unseen codons as stop
    for a in 'ACGT':
        for b in 'ACGT':
            for c in 'ACGT':
                cdn = a + b + c
                if cdn not in table:
                    table[cdn] = '*'

    print(f"Final table: {len(table)} codons")

    # Verify against training data
    ok = sum(
        1 for dna, prot in training_pairs
        if translate(get_codons(dna), table, subs) == prot
    )
    print(f"Training verification: {ok}/{len(training_pairs)} correct")

    # Step 10: Translate test sequences
    os.makedirs('/app/results', exist_ok=True)
    results = []
    for gid in test_ids:
        dna = genes[gid][0]
        cdns = get_codons(dna)
        results.append(translate(cdns, table, subs))

    with open(out_prot, 'w') as f:
        for r in results:
            f.write(r + '\n')
    print(f"Wrote {len(results)} translations -> {out_prot}")

    with open(out_table, 'w') as f:
        for cdn in sorted(table):
            f.write(f"{cdn}\t{table[cdn]}\n")
    print(f"Wrote codon table -> {out_table}")


if __name__ == '__main__':
    main()
