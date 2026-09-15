#!/usr/bin/env python3
"""
Custom variant effect predictor.

Parses a reference FASTA, GFF3 gene annotations, and a VCF file.
Annotates each variant with gene overlap, feature type, functional effect,
and amino acid change.

Handles:
- Multi-exon genes (intron splicing)
- Reverse-strand genes (reverse complement)
- Indel left-normalization
- 11 variant effect categories
- HGVS-like amino acid change notation
"""

import argparse
import sys
import os

CODON_TABLE = {
    'TTT': 'Phe', 'TTC': 'Phe', 'TTA': 'Leu', 'TTG': 'Leu',
    'CTT': 'Leu', 'CTC': 'Leu', 'CTA': 'Leu', 'CTG': 'Leu',
    'ATT': 'Ile', 'ATC': 'Ile', 'ATA': 'Ile', 'ATG': 'Met',
    'GTT': 'Val', 'GTC': 'Val', 'GTA': 'Val', 'GTG': 'Val',
    'TCT': 'Ser', 'TCC': 'Ser', 'TCA': 'Ser', 'TCG': 'Ser',
    'CCT': 'Pro', 'CCC': 'Pro', 'CCA': 'Pro', 'CCG': 'Pro',
    'ACT': 'Thr', 'ACC': 'Thr', 'ACA': 'Thr', 'ACG': 'Thr',
    'GCT': 'Ala', 'GCC': 'Ala', 'GCA': 'Ala', 'GCG': 'Ala',
    'TAT': 'Tyr', 'TAC': 'Tyr', 'TAA': 'Ter', 'TAG': 'Ter',
    'CAT': 'His', 'CAC': 'His', 'CAA': 'Gln', 'CAG': 'Gln',
    'AAT': 'Asn', 'AAC': 'Asn', 'AAA': 'Lys', 'AAG': 'Lys',
    'GAT': 'Asp', 'GAC': 'Asp', 'GAA': 'Glu', 'GAG': 'Glu',
    'TGT': 'Cys', 'TGC': 'Cys', 'TGA': 'Ter', 'TGG': 'Trp',
    'CGT': 'Arg', 'CGC': 'Arg', 'CGA': 'Arg', 'CGG': 'Arg',
    'AGT': 'Ser', 'AGC': 'Ser', 'AGA': 'Arg', 'AGG': 'Arg',
    'GGT': 'Gly', 'GGC': 'Gly', 'GGA': 'Gly', 'GGG': 'Gly',
}

RC_MAP = {'A': 'T', 'T': 'A', 'C': 'G', 'G': 'C', 'N': 'N'}


def revcomp(seq):
    return ''.join(RC_MAP[c] for c in reversed(seq))


def parse_fasta(path):
    """Parse FASTA file into dict of {chrom: sequence}."""
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
    """Parse GFF3 into gene models.

    Returns list of gene dicts with:
        name, chrom, strand, gene_start, gene_end,
        cds_regions: list of (start, end) 1-based inclusive,
        exon_regions: list of (start, end)
    """
    genes = {}
    cds_to_gene = {}
    exon_to_gene = {}

    with open(path) as f:
        for line in f:
            if line.startswith('#'):
                continue
            parts = line.strip().split('\t')
            if len(parts) < 9:
                continue
            chrom, _, ftype, start, end, _, strand, phase, attrs = parts
            start, end = int(start), int(end)

            attr_dict = {}
            for attr in attrs.split(';'):
                if '=' in attr:
                    k, v = attr.split('=', 1)
                    attr_dict[k] = v

            if ftype == 'gene':
                name = attr_dict.get('Name', attr_dict.get('ID', ''))
                gene_id = attr_dict.get('ID', '')
                genes[gene_id] = {
                    'name': name,
                    'chrom': chrom,
                    'strand': strand,
                    'gene_start': start,
                    'gene_end': end,
                    'cds_regions': [],
                    'exon_regions': [],
                }
            elif ftype == 'mRNA':
                parent = attr_dict.get('Parent', '')
                mrna_id = attr_dict.get('ID', '')
                if parent.startswith('gene_'):
                    cds_to_gene[mrna_id] = parent
            elif ftype == 'CDS':
                parent = attr_dict.get('Parent', '')
                gene_id = cds_to_gene.get(parent, '')
                if gene_id in genes:
                    genes[gene_id]['cds_regions'].append((start, end))
            elif ftype == 'exon':
                parent = attr_dict.get('Parent', '')
                gene_id = cds_to_gene.get(parent, '')
                if gene_id in genes:
                    genes[gene_id]['exon_regions'].append((start, end))

    result = list(genes.values())
    # Sort CDS regions by start position
    for g in result:
        g['cds_regions'].sort()
        g['exon_regions'].sort()
    return result


def parse_vcf(path):
    """Parse VCF file into list of variant dicts."""
    variants = []
    with open(path) as f:
        for line in f:
            if line.startswith('#'):
                continue
            parts = line.strip().split('\t')
            if len(parts) < 8:
                continue
            chrom, pos, vid, ref, alt, qual, filt, info = parts[:8]
            variants.append({
                'chrom': chrom,
                'pos': int(pos),
                'id': vid,
                'ref': ref.upper(),
                'alt': alt.upper(),
            })
    return variants


def left_normalize(chrom_seq, pos, ref, alt):
    """Left-normalize using a clean implementation.

    Algorithm:
    1. While right bases match, trim them
    2. While left base matches and both have >1 base, trim and advance pos
    3. While the variant can be shifted left (last base of indel == base before pos), shift
    """
    if len(ref) == 1 and len(alt) == 1:
        return pos, ref, alt

    r = ref
    a = alt
    p = pos  # 1-based

    # Trim matching suffix
    while len(r) > 1 and len(a) > 1 and r[-1] == a[-1]:
        r = r[:-1]
        a = a[:-1]

    # Trim matching prefix
    while len(r) > 1 and len(a) > 1 and r[0] == a[0]:
        r = r[1:]
        a = a[1:]
        p += 1

    # Now we have the minimal representation with anchor base
    # Left-shift: for deletions like pos=122 GC>G, check if we can shift left
    # The anchor base and first deleted/inserted base pattern
    if len(r) > len(a) and len(a) == 1:
        # Deletion: r = anchor + deleted_bases, a = anchor
        anchor = r[0]
        deleted = r[1:]
        while p > 1:
            prev_base = chrom_seq[p - 2]  # 0-based index of base before current pos
            if deleted[-1] == prev_base:
                # Can shift left: rotate deleted bases
                deleted = prev_base + deleted[:-1]
                p -= 1
                r = chrom_seq[p - 1] + deleted  # new anchor + rotated deleted
                a = chrom_seq[p - 1]  # new anchor
            else:
                break
    elif len(a) > len(r) and len(r) == 1:
        # Insertion: r = anchor, a = anchor + inserted_bases
        inserted = a[1:]
        while p > 1:
            prev_base = chrom_seq[p - 2]
            if inserted[-1] == prev_base:
                inserted = prev_base + inserted[:-1]
                p -= 1
                r = chrom_seq[p - 1]
                a = chrom_seq[p - 1] + inserted
            else:
                break

    return p, r, a


def get_spliced_cds(gene, ref_seqs):
    """Get the spliced CDS sequence for a gene.

    For + strand: concatenate CDS regions in order.
    For - strand: concatenate CDS regions in reverse order and reverse complement.
    """
    chrom_seq = ref_seqs[gene['chrom']]
    cds_regions = gene['cds_regions']  # sorted by start

    if gene['strand'] == '+':
        cds = ''
        for start, end in cds_regions:
            cds += chrom_seq[start-1:end]  # 1-based to 0-based
        return cds
    else:
        # Reverse strand: CDS regions in reverse order, then reverse complement
        cds = ''
        for start, end in reversed(cds_regions):
            cds += chrom_seq[start-1:end]
        return revcomp(cds)


def get_cds_offset(gene, genomic_pos):
    """Get the 0-based offset of a genomic position in the spliced CDS.

    Returns (offset, total_cds_len) or (None, total_cds_len) if not in CDS.
    """
    cds_regions = gene['cds_regions']

    if gene['strand'] == '+':
        offset = 0
        for start, end in cds_regions:
            if start <= genomic_pos <= end:
                return offset + (genomic_pos - start), None
            offset += (end - start + 1)
        return None, offset
    else:
        # Reverse strand: position 1350 maps to offset 0, position 1051 maps to offset 299
        # CDS regions sorted by start. For - strand, the CDS reads from the highest position down.
        offset = 0
        for start, end in reversed(cds_regions):
            if start <= genomic_pos <= end:
                return offset + (end - genomic_pos), None
            offset += (end - start + 1)
        return None, offset


def classify_position(gene, genomic_pos):
    """Classify a genomic position relative to a gene.

    Returns one of: 'CDS', 'intron', 'splice_site_donor', 'splice_site_acceptor'
    """
    # Check if in any CDS region
    for start, end in gene['cds_regions']:
        if start <= genomic_pos <= end:
            return 'CDS'

    # Check if in intron (between exons, within gene boundaries)
    exon_regions = gene['exon_regions'] if gene['exon_regions'] else gene['cds_regions']

    for i in range(len(exon_regions) - 1):
        intron_start = exon_regions[i][1] + 1
        intron_end = exon_regions[i + 1][0] - 1

        if intron_start <= genomic_pos <= intron_end:
            # Check splice sites (first 2 and last 2 bases of intron)
            if gene['strand'] == '+':
                if genomic_pos <= intron_start + 1:
                    return 'splice_site_donor'
                elif genomic_pos >= intron_end - 1:
                    return 'splice_site_acceptor'
            else:
                # For - strand, donor is at the high end, acceptor at the low end
                if genomic_pos >= intron_end - 1:
                    return 'splice_site_donor'
                elif genomic_pos <= intron_start + 1:
                    return 'splice_site_acceptor'
            return 'intron'

    return None  # Not in this gene


def annotate_variant(variant, genes, ref_seqs):
    """Annotate a single variant.

    Returns dict with gene, feature, effect, aa_change.
    """
    chrom = variant['chrom']
    pos = variant['pos']
    ref = variant['ref']
    alt = variant['alt']
    chrom_seq = ref_seqs[chrom]

    # Left-normalize indels
    pos, ref, alt = left_normalize(chrom_seq, pos, ref, alt)

    # Determine which gene(s) the variant overlaps
    overlapping_gene = None
    for gene in genes:
        if gene['chrom'] != chrom:
            continue
        if gene['gene_start'] <= pos <= gene['gene_end']:
            overlapping_gene = gene
            break

    result = {
        'chrom': chrom,
        'pos': pos,
        'ref': ref,
        'alt': alt,
        'gene': '.',
        'feature': 'intergenic',
        'effect': 'intergenic_variant',
        'aa_change': '.',
    }

    if overlapping_gene is None:
        return result

    gene = overlapping_gene
    result['gene'] = gene['name']

    # Classify position
    pos_class = classify_position(gene, pos)

    if pos_class is None:
        result['feature'] = 'intergenic'
        result['effect'] = 'intergenic_variant'
        result['gene'] = '.'
        return result

    if pos_class == 'intron':
        result['feature'] = 'intron'
        result['effect'] = 'intron_variant'
        return result

    if pos_class == 'splice_site_donor':
        result['feature'] = 'splice_site'
        result['effect'] = 'splice_donor_variant'
        return result

    if pos_class == 'splice_site_acceptor':
        result['feature'] = 'splice_site'
        result['effect'] = 'splice_acceptor_variant'
        return result

    # CDS variant
    result['feature'] = 'CDS'

    is_snp = len(ref) == 1 and len(alt) == 1

    if not is_snp:
        # Indel in CDS
        indel_len = len(alt) - len(ref)
        if indel_len % 3 == 0:
            if indel_len < 0:
                # Deletion
                result['effect'] = 'inframe_deletion'
                # Determine which amino acid(s) are deleted
                # The deletion removes bases ref[1:] (after anchor)
                # Find the CDS offset of the first deleted base
                del_start_genomic = pos + 1  # first deleted base (after anchor)
                cds_offset, _ = get_cds_offset(gene, del_start_genomic)
                if cds_offset is not None:
                    spliced_cds = get_spliced_cds(gene, ref_seqs)
                    codon_num = cds_offset // 3
                    codon_start = codon_num * 3
                    deleted_len = abs(indel_len)
                    # Get the deleted amino acids
                    deleted_codons = spliced_cds[codon_start:codon_start + deleted_len]
                    if len(deleted_codons) >= 3:
                        aa = CODON_TABLE.get(deleted_codons[:3], 'X')
                        result['aa_change'] = f"p.{aa}{codon_num + 1}del"
            else:
                # Insertion
                result['effect'] = 'inframe_insertion'
                # Determine inserted amino acid
                inserted_bases = alt[1:]  # bases inserted after anchor
                if gene['strand'] == '-':
                    inserted_bases = revcomp(inserted_bases)
                if len(inserted_bases) >= 3:
                    ins_aa = CODON_TABLE.get(inserted_bases[:3], 'X')
                    # Find position in protein
                    cds_offset, _ = get_cds_offset(gene, pos)
                    if cds_offset is not None:
                        codon_num = cds_offset // 3
                        result['aa_change'] = f"p.{codon_num + 1}_{codon_num + 2}ins{ins_aa}"
        else:
            result['effect'] = 'frameshift_variant'

        return result

    # SNP in CDS
    cds_offset, _ = get_cds_offset(gene, pos)
    if cds_offset is None:
        result['effect'] = 'missense_variant'
        return result

    spliced_cds = get_spliced_cds(gene, ref_seqs)
    codon_num = cds_offset // 3
    codon_pos = cds_offset % 3
    codon_start = codon_num * 3

    ref_codon = spliced_cds[codon_start:codon_start + 3]
    if len(ref_codon) < 3:
        result['effect'] = 'missense_variant'
        return result

    # For reverse strand, complement the alt base
    if gene['strand'] == '-':
        alt_base_cds = RC_MAP[alt]
    else:
        alt_base_cds = alt

    alt_codon = list(ref_codon)
    alt_codon[codon_pos] = alt_base_cds
    alt_codon = ''.join(alt_codon)

    ref_aa = CODON_TABLE.get(ref_codon, 'X')
    alt_aa = CODON_TABLE.get(alt_codon, 'X')
    aa_pos = codon_num + 1  # 1-based

    if ref_aa == 'Met' and aa_pos == 1 and alt_aa != 'Met':
        result['effect'] = 'start_lost'
        result['aa_change'] = f"p.Met1{alt_aa}"
    elif ref_aa == alt_aa:
        result['effect'] = 'synonymous_variant'
        result['aa_change'] = f"p.{ref_aa}{aa_pos}{alt_aa}"
    elif alt_aa == 'Ter':
        result['effect'] = 'stop_gained'
        result['aa_change'] = f"p.{ref_aa}{aa_pos}Ter"
    elif ref_aa == 'Ter':
        result['effect'] = 'stop_lost'
        result['aa_change'] = f"p.Ter{aa_pos}{alt_aa}"
    else:
        result['effect'] = 'missense_variant'
        result['aa_change'] = f"p.{ref_aa}{aa_pos}{alt_aa}"

    return result


def main():
    parser = argparse.ArgumentParser(description='Variant Effect Predictor')
    parser.add_argument('--reference', required=True)
    parser.add_argument('--gff3', required=True)
    parser.add_argument('--vcf', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()

    ref_seqs = parse_fasta(args.reference)
    genes = parse_gff3(args.gff3)
    variants = parse_vcf(args.vcf)

    results = []
    for var in variants:
        result = annotate_variant(var, genes, ref_seqs)
        results.append(result)

    # Sort by position
    results.sort(key=lambda r: r['pos'])

    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    with open(args.output, 'w') as f:
        f.write('CHROM\tPOS\tREF\tALT\tGENE\tFEATURE\tEFFECT\tAA_CHANGE\n')
        for r in results:
            f.write(f"{r['chrom']}\t{r['pos']}\t{r['ref']}\t{r['alt']}\t"
                    f"{r['gene']}\t{r['feature']}\t{r['effect']}\t{r['aa_change']}\n")

    print(f"Wrote {len(results)} variant annotations to {args.output}")


if __name__ == '__main__':
    main()
