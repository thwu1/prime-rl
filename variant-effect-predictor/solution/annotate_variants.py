#!/usr/bin/env python3
"""
Variant annotation pipeline: QC, normalization, and functional effect prediction.

Reads the raw VCF, performs quality control (REF check, multi-allelic splitting,
indel left-alignment), annotates each clean variant with functional effects on
encoded proteins, and produces summary statistics.

"""
import json
import os

GENETIC_CODE = {
    'TTT': 'F', 'TTC': 'F', 'TTA': 'L', 'TTG': 'L',
    'CTT': 'L', 'CTC': 'L', 'CTA': 'L', 'CTG': 'L',
    'ATT': 'I', 'ATC': 'I', 'ATA': 'I', 'ATG': 'M',
    'GTT': 'V', 'GTC': 'V', 'GTA': 'V', 'GTG': 'V',
    'TCT': 'S', 'TCC': 'S', 'TCA': 'S', 'TCG': 'S',
    'CCT': 'P', 'CCC': 'P', 'CCA': 'P', 'CCG': 'P',
    'ACT': 'T', 'ACC': 'T', 'ACA': 'T', 'ACG': 'T',
    'GCT': 'A', 'GCC': 'A', 'GCA': 'A', 'GCG': 'A',
    'TAT': 'Y', 'TAC': 'Y', 'TAA': '*', 'TAG': '*',
    'CAT': 'H', 'CAC': 'H', 'CAA': 'Q', 'CAG': 'Q',
    'AAT': 'N', 'AAC': 'N', 'AAA': 'K', 'AAG': 'K',
    'GAT': 'D', 'GAC': 'D', 'GAA': 'E', 'GAG': 'E',
    'TGT': 'C', 'TGC': 'C', 'TGA': '*', 'TGG': 'W',
    'CGT': 'R', 'CGC': 'R', 'CGA': 'R', 'CGG': 'R',
    'AGT': 'S', 'AGC': 'S', 'AGA': 'R', 'AGG': 'R',
    'GGT': 'G', 'GGC': 'G', 'GGA': 'G', 'GGG': 'G',
}

COMPLEMENT = {'A': 'T', 'T': 'A', 'C': 'G', 'G': 'C', 'N': 'N'}


def revcomp(s):
    return ''.join(COMPLEMENT[b] for b in reversed(s))


def parse_fasta(path):
    seqs = {}
    name = None
    parts = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith('>'):
                if name is not None:
                    seqs[name] = ''.join(parts)
                name = line[1:].split()[0]
                parts = []
            else:
                parts.append(line.upper())
    if name is not None:
        seqs[name] = ''.join(parts)
    return seqs


def parse_gff3(path):
    features = []
    with open(path) as f:
        for line in f:
            if line.startswith('#'):
                continue
            fields = line.strip().split('\t')
            if len(fields) < 9:
                continue
            attrs = {}
            for attr in fields[8].split(';'):
                if '=' in attr:
                    k, v = attr.split('=', 1)
                    attrs[k] = v
            features.append({
                'chrom': fields[0], 'type': fields[2],
                'start': int(fields[3]), 'end': int(fields[4]),
                'strand': fields[6], 'attrs': attrs
            })

    genes = {}
    gene_list = []
    for feat in features:
        if feat['type'] == 'gene':
            gene = {
                'id': feat['attrs'].get('ID', ''),
                'name': feat['attrs'].get('Name', feat['attrs'].get('ID', '')),
                'chrom': feat['chrom'],
                'start': feat['start'], 'end': feat['end'],
                'strand': feat['strand'],
                'exons': [], 'cds_regions': [],
            }
            genes[gene['id']] = gene
            gene_list.append(gene)

    mrna_to_gene = {}
    for feat in features:
        if feat['type'] == 'mRNA':
            mrna_to_gene[feat['attrs'].get('ID', '')] = feat['attrs'].get('Parent', '')

    for feat in features:
        parent = feat['attrs'].get('Parent', '')
        gene_id = mrna_to_gene.get(parent, parent)
        if gene_id not in genes:
            continue
        gene = genes[gene_id]
        if feat['type'] == 'exon':
            gene['exons'].append((feat['start'], feat['end']))
        elif feat['type'] == 'CDS':
            gene['cds_regions'].append((feat['start'], feat['end']))

    for gene in gene_list:
        gene['exons'].sort()
        gene['cds_regions'].sort()
    return gene_list


def parse_raw_vcf(path):
    """Parse raw VCF file, returning list of variant dicts."""
    variants = []
    with open(path) as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            fields = line.strip().split('\t')
            if len(fields) < 5:
                continue
            variants.append({
                'chrom': fields[0],
                'pos': int(fields[1]),
                'ref': fields[3],
                'alt': fields[4],
            })
    return variants


def check_ref_allele(var, genome):
    """Check if REF allele matches reference genome. Returns True if match."""
    chrom_seq = genome.get(var['chrom'], '')
    ref = var['ref']
    genome_ref = chrom_seq[var['pos'] - 1:var['pos'] - 1 + len(ref)]
    return genome_ref.upper() == ref.upper()


def split_multiallelic(variants):
    """Split multi-allelic records into biallelic. Returns (split_list, count)."""
    result = []
    split_count = 0
    for var in variants:
        if ',' in var['alt']:
            split_count += 1
            for alt in var['alt'].split(','):
                result.append({
                    'chrom': var['chrom'],
                    'pos': var['pos'],
                    'ref': var['ref'],
                    'alt': alt.strip(),
                })
        else:
            result.append(var.copy())
    return result, split_count


def left_align_indel(chrom_seq, pos, ref, alt):
    """Left-align an indel variant.

    For an insertion (e.g. G -> GG at pos 1615), the inserted base(s) are
    shifted leftward while the preceding reference base matches the last
    inserted base, and the anchor base is updated to the new position.

    Returns (new_pos, new_ref, new_alt, changed).
    """
    # SNPs and MNPs don't need alignment
    if len(ref) == len(alt):
        return pos, ref, alt, False

    orig_pos = pos

    if len(ref) == 1 and len(alt) > 1:
        # Insertion: ref = anchor base, alt = anchor + inserted bases
        inserted = alt[1:]
        anchor_pos = pos

        while anchor_pos > 1:
            preceding_base = chrom_seq[anchor_pos - 2]  # 0-indexed
            if preceding_base != inserted[-1]:
                break
            # Rotate inserted bases: move preceding base to front, drop last
            inserted = preceding_base + inserted[:-1]
            anchor_pos -= 1

        new_ref = chrom_seq[anchor_pos - 1]
        new_alt = new_ref + inserted
        return anchor_pos, new_ref, new_alt, (anchor_pos != orig_pos)

    elif len(ref) > 1 and len(alt) == 1:
        # Deletion: ref = anchor + deleted bases, alt = anchor
        deleted = ref[1:]
        anchor_pos = pos

        while anchor_pos > 1:
            preceding_base = chrom_seq[anchor_pos - 2]
            if preceding_base != deleted[-1]:
                break
            deleted = preceding_base + deleted[:-1]
            anchor_pos -= 1

        new_ref = chrom_seq[anchor_pos - 1] + deleted
        new_alt = chrom_seq[anchor_pos - 1]
        return anchor_pos, new_ref, new_alt, (anchor_pos != orig_pos)

    # Complex indel - don't normalize
    return pos, ref, alt, False


def find_introns(gene):
    introns = []
    exons = sorted(gene['exons'])
    for i in range(len(exons) - 1):
        intron_start = exons[i][1] + 1
        intron_end = exons[i + 1][0] - 1
        if intron_start <= intron_end:
            introns.append((intron_start, intron_end))
    return introns


def get_cds_sequence(gene, genome_seq):
    cds_parts = []
    for start, end in gene['cds_regions']:
        cds_parts.append(genome_seq[start - 1:end])
    cds_genomic = ''.join(cds_parts)
    if gene['strand'] == '-':
        return revcomp(cds_genomic)
    return cds_genomic


def genomic_pos_to_cds_pos(gene, pos):
    if gene['strand'] == '+':
        cds_offset = 0
        for cds_start, cds_end in gene['cds_regions']:
            if cds_start <= pos <= cds_end:
                return cds_offset + (pos - cds_start)
            cds_offset += (cds_end - cds_start + 1)
        return None
    else:
        cds_offset = 0
        for cds_start, cds_end in reversed(gene['cds_regions']):
            if cds_start <= pos <= cds_end:
                return cds_offset + (cds_end - pos)
            cds_offset += (cds_end - cds_start + 1)
        return None


def annotate_variant(var, genes, genome):
    chrom = var['chrom']
    pos = var['pos']
    ref = var['ref']
    alt = var['alt']
    seq = genome[chrom]

    result = {
        'CHROM': chrom, 'POS': str(pos), 'REF': ref, 'ALT': alt,
        'GENE': '.', 'EFFECT': 'intergenic_variant',
        'CODON_REF': '.', 'CODON_ALT': '.',
        'AA_REF': '.', 'AA_ALT': '.', 'AA_POS': '.'
    }

    overlapping_gene = None
    for gene in genes:
        if gene['chrom'] == chrom and gene['start'] <= pos <= gene['end']:
            overlapping_gene = gene
            break

    if overlapping_gene is None:
        return result

    gene = overlapping_gene
    result['GENE'] = gene['name']

    in_cds = any(s <= pos <= e for s, e in gene['cds_regions'])

    if not in_cds:
        introns = find_introns(gene)
        for intron_start, intron_end in introns:
            if pos in (intron_start, intron_start + 1):
                result['EFFECT'] = 'splice_donor_variant'
                return result
            if pos in (intron_end - 1, intron_end):
                result['EFFECT'] = 'splice_acceptor_variant'
                return result
        result['EFFECT'] = 'intron_variant'
        return result

    is_snp = len(ref) == 1 and len(alt) == 1

    if not is_snp:
        result['EFFECT'] = 'frameshift_variant'
        return result

    cds_pos = genomic_pos_to_cds_pos(gene, pos)
    if cds_pos is None:
        result['EFFECT'] = 'intron_variant'
        return result

    cds_seq = get_cds_sequence(gene, seq)
    codon_num = cds_pos // 3 + 1
    codon_offset = cds_pos % 3
    codon_start = (cds_pos // 3) * 3

    ref_codon = cds_seq[codon_start:codon_start + 3]
    if len(ref_codon) < 3:
        result['EFFECT'] = 'missense_variant'
        return result

    if gene['strand'] == '+':
        mrna_alt = alt
    else:
        mrna_alt = COMPLEMENT[alt]

    alt_codon = list(ref_codon)
    alt_codon[codon_offset] = mrna_alt
    alt_codon = ''.join(alt_codon)

    ref_aa = GENETIC_CODE.get(ref_codon, '?')
    alt_aa = GENETIC_CODE.get(alt_codon, '?')

    result['CODON_REF'] = ref_codon
    result['CODON_ALT'] = alt_codon
    result['AA_REF'] = ref_aa
    result['AA_ALT'] = alt_aa
    result['AA_POS'] = str(codon_num)

    if alt_aa == '*':
        result['EFFECT'] = 'stop_gained'
    elif ref_aa == alt_aa:
        result['EFFECT'] = 'synonymous_variant'
    else:
        result['EFFECT'] = 'missense_variant'

    return result


def is_transition(ref, alt):
    return (ref, alt) in {('A', 'G'), ('G', 'A'), ('C', 'T'), ('T', 'C')}


def main():
    genome = parse_fasta("/app/reference.fa")
    genes = parse_gff3("/app/annotations.gff3")

    # ---- QC Pipeline ----

    # Step 1: Parse raw VCF
    raw_variants = parse_raw_vcf("/app/variants.vcf")
    total_input = len(raw_variants)

    # Step 2: Exclude REF-allele mismatches
    ref_mismatches = 0
    valid_variants = []
    for var in raw_variants:
        if check_ref_allele(var, genome):
            valid_variants.append(var)
        else:
            ref_mismatches += 1

    # Step 3: Split multi-allelic records
    split_variants, multiallelic_count = split_multiallelic(valid_variants)

    # Step 4: Left-align indels
    indels_realigned = 0
    for var in split_variants:
        seq = genome.get(var['chrom'], '')
        new_pos, new_ref, new_alt, changed = left_align_indel(
            seq, var['pos'], var['ref'], var['alt'])
        if changed:
            indels_realigned += 1
        var['pos'] = new_pos
        var['ref'] = new_ref
        var['alt'] = new_alt

    # Step 5: Sort by position
    split_variants.sort(key=lambda v: v['pos'])

    total_clean = len(split_variants)

    # ---- QC Report ----
    qc = {
        "ref_mismatches": ref_mismatches,
        "multiallelic_split": multiallelic_count,
        "indels_realigned": indels_realigned,
        "total_input_variants": total_input,
        "total_clean_variants": total_clean,
    }

    # ---- Annotation ----
    results = []
    ti_count = 0
    tv_count = 0
    effect_counts = {}
    genes_with_cds_variant = set()
    cds_effects = {'synonymous_variant', 'missense_variant',
                   'stop_gained', 'frameshift_variant'}

    for var in split_variants:
        ann = annotate_variant(var, genes, genome)
        results.append(ann)

        if len(var['ref']) == 1 and len(var['alt']) == 1:
            if is_transition(var['ref'], var['alt']):
                ti_count += 1
            else:
                tv_count += 1

        effect = ann['EFFECT']
        effect_counts[effect] = effect_counts.get(effect, 0) + 1

        if effect in cds_effects and ann['GENE'] != '.':
            genes_with_cds_variant.add(ann['GENE'])

    # ---- Write Outputs ----
    os.makedirs("/app/results", exist_ok=True)

    with open("/app/results/qc_report.json", "w") as f:
        json.dump(qc, f, indent=2)

    columns = ['CHROM', 'POS', 'REF', 'ALT', 'GENE', 'EFFECT',
               'CODON_REF', 'CODON_ALT', 'AA_REF', 'AA_ALT', 'AA_POS']
    with open("/app/results/variant_effects.tsv", "w") as f:
        f.write("\t".join(columns) + "\n")
        for r in results:
            f.write("\t".join(r[c] for c in columns) + "\n")

    titv = round(ti_count / tv_count, 2) if tv_count > 0 else 0.0
    summary = {
        "effect_counts": effect_counts,
        "titv_ratio": titv,
        "genes_affected": sorted(genes_with_cds_variant),
    }
    with open("/app/results/summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"Annotated {len(results)} variants")
    print(f"Ti={ti_count}, Tv={tv_count}, Ti/Tv={titv}")


if __name__ == "__main__":
    main()
