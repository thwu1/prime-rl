#!/usr/bin/env python3
"""
Classify variant functional effects using gene overlap data from bedtools
and reference genome sequence.

Pipeline step 5: Takes normalized VCF, bedtools intersection output,
reference genome, and GFF3 annotations to produce final effect classifications.
"""

import argparse
import sys

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

COMPLEMENT = {'A': 'T', 'T': 'A', 'C': 'G', 'G': 'C', 'N': 'N'}


def revcomp(seq):
    """Reverse complement a DNA sequence."""
    return ''.join(COMPLEMENT[c] for c in reversed(seq))


def parse_fasta(path):
    """Parse FASTA file into {name: sequence} dict."""
    seqs = {}
    name = None
    parts = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith('>'):
                if name:
                    seqs[name] = ''.join(parts)
                name = line[1:].split()[0]
                parts = []
            else:
                parts.append(line.upper())
    if name:
        seqs[name] = ''.join(parts)
    return seqs


def parse_gff3_genes(path):
    """Parse GFF3 to extract gene models with CDS and exon coordinates."""
    genes_by_id = {}
    genes_by_name = {}
    mrna_to_gene = {}

    with open(path) as f:
        for line in f:
            if line.startswith('#'):
                continue
            parts = line.strip().split('\t')
            if len(parts) < 9:
                continue
            chrom, _, ftype, start, end, _, strand, _, attrs_str = parts
            start, end = int(start), int(end)

            attrs = {}
            for a in attrs_str.split(';'):
                if '=' in a:
                    k, v = a.split('=', 1)
                    attrs[k] = v

            if ftype == 'gene':
                gene_id = attrs.get('ID', '')
                name = attrs.get('Name', gene_id)
                gene_data = {
                    'name': name,
                    'chrom': chrom,
                    'strand': strand,
                    'gene_start': start,
                    'gene_end': end,
                    'cds_regions': [],
                    'exon_regions': [],
                }
                genes_by_id[gene_id] = gene_data
                genes_by_name[name] = gene_data
            elif ftype == 'mRNA':
                mrna_id = attrs.get('ID', '')
                parent = attrs.get('Parent', '')
                mrna_to_gene[mrna_id] = parent
            elif ftype == 'CDS':
                parent = attrs.get('Parent', '')
                gene_id = mrna_to_gene.get(parent, '')
                if gene_id in genes_by_id:
                    genes_by_id[gene_id]['cds_regions'].append((start, end))
            elif ftype == 'exon':
                parent = attrs.get('Parent', '')
                gene_id = mrna_to_gene.get(parent, '')
                if gene_id in genes_by_id:
                    genes_by_id[gene_id]['exon_regions'].append((start, end))

    for g in genes_by_name.values():
        g['cds_regions'].sort()
        g['exon_regions'].sort()

    return genes_by_name


def parse_vcf(path):
    """Parse VCF file into list of variant records."""
    variants = []
    with open(path) as f:
        for line in f:
            if line.startswith('#'):
                continue
            parts = line.strip().split('\t')
            if len(parts) < 5:
                continue
            variants.append({
                'chrom': parts[0],
                'pos': int(parts[1]),
                'id': parts[2],
                'ref': parts[3].upper(),
                'alt': parts[4].upper(),
            })
    return variants


def parse_intersected(path):
    """Parse bedtools intersect output to determine gene overlap for each variant.

    Expected columns (from -wa -wb):
    var_chr var_start var_end var_id var_ref var_alt gene_chr gene_start gene_end gene_name . gene_strand
    """
    overlaps = {}
    with open(path) as f:
        for line in f:
            fields = line.strip().split('\t')
            if len(fields) < 12:
                continue
            var_id = fields[3]
            gene_name = fields[9]
            if gene_name != '.':
                overlaps[var_id] = gene_name
    return overlaps


def get_cds_offset(gene, pos):
    """Compute 0-based offset of a genomic position within the CDS.

    For forward strand: offset from start of gene.
    For reverse strand: offset from end of gene.
    """
    if gene['strand'] == '+':
        return pos - gene['gene_start']
    else:
        return gene['gene_end'] - pos


def classify_variant(var, gene, ref_seqs):
    """Classify a single variant's effect within a gene.

    Returns (feature, effect, aa_change) tuple.
    """
    pos = var['pos']
    ref = var['ref']
    alt = var['alt']
    chrom_seq = ref_seqs[var['chrom']]

    # Check if position falls within a CDS region
    in_cds = False
    for cds_start, cds_end in gene['cds_regions']:
        if cds_start <= pos <= cds_end:
            in_cds = True
            break

    if not in_cds:
        # Check for intron / splice site
        exons = gene['exon_regions'] if gene['exon_regions'] else gene['cds_regions']
        for i in range(len(exons) - 1):
            intron_start = exons[i][1] + 1
            intron_end = exons[i + 1][0] - 1
            if intron_start <= pos <= intron_end:
                # Splice donor: first 2 bases of intron
                if pos <= intron_start + 1:
                    return 'splice_site', 'splice_donor_variant', '.'
                # Splice acceptor: last 2 bases of intron
                elif pos >= intron_end - 1:
                    return 'splice_site', 'splice_acceptor_variant', '.'
                else:
                    return 'intron', 'intron_variant', '.'
        return None, None, None

    # CDS variant
    is_snp = len(ref) == 1 and len(alt) == 1

    if not is_snp:
        # Indel in CDS
        indel_len = len(alt) - len(ref)
        if indel_len % 3 == 0:
            if indel_len < 0:
                # Inframe deletion
                del_start = pos + 1
                cds_off = get_cds_offset(gene, del_start)
                codon_num = cds_off // 3
                if gene['strand'] == '+':
                    codon_start = gene['gene_start'] + codon_num * 3
                    codon = chrom_seq[codon_start - 1:codon_start + 2]
                else:
                    codon_end = gene['gene_end'] - codon_num * 3
                    codon = revcomp(chrom_seq[codon_end - 3:codon_end])
                aa = CODON_TABLE.get(codon, 'X')
                return 'CDS', 'inframe_deletion', f'p.{aa}{codon_num + 1}del'
            else:
                # Inframe insertion
                ins_bases = alt[1:]
                if gene['strand'] == '-':
                    ins_bases = revcomp(ins_bases)
                ins_aa = CODON_TABLE.get(ins_bases[:3], 'X') if len(ins_bases) >= 3 else 'X'
                cds_off = get_cds_offset(gene, pos)
                codon_num = cds_off // 3
                return 'CDS', 'inframe_insertion', f'p.{codon_num + 1}_{codon_num + 2}ins{ins_aa}'
        else:
            return 'CDS', 'frameshift_variant', '.'

    # SNP in CDS — determine codon and amino acid change
    cds_off = get_cds_offset(gene, pos)
    codon_num = cds_off // 3
    codon_pos = cds_off % 3

    if gene['strand'] == '+':
        codon_start = gene['gene_start'] + codon_num * 3
        ref_codon = chrom_seq[codon_start - 1:codon_start + 2]
        mut_codon = list(ref_codon)
        mut_codon[codon_pos] = alt
        mut_codon = ''.join(mut_codon)
    else:
        # Reverse strand: extract forward-strand codon, reverse-complement it
        codon_end = gene['gene_end'] - codon_num * 3
        ref_codon_fwd = chrom_seq[codon_end - 3:codon_end]
        ref_codon = revcomp(ref_codon_fwd)
        mut_codon = list(ref_codon)
        mut_codon[codon_pos] = alt
        mut_codon = ''.join(mut_codon)

    ref_aa = CODON_TABLE.get(ref_codon, 'X')
    mut_aa = CODON_TABLE.get(mut_codon, 'X')
    aa_pos = codon_num + 1

    if ref_aa == 'Met' and aa_pos == 1 and mut_aa != 'Met':
        return 'CDS', 'start_lost', f'p.Met1{mut_aa}'
    elif ref_aa == mut_aa:
        return 'CDS', 'synonymous_variant', f'p.{ref_aa}{aa_pos}{mut_aa}'
    elif mut_aa == 'Ter':
        return 'CDS', 'stop_gained', f'p.{ref_aa}{aa_pos}Ter'
    else:
        return 'CDS', 'missense_variant', f'p.{ref_aa}{aa_pos}{mut_aa}'


def main():
    parser = argparse.ArgumentParser(description='Classify variant effects')
    parser.add_argument('--vcf', required=True, help='Normalized VCF file')
    parser.add_argument('--intersected', required=True, help='bedtools intersect output')
    parser.add_argument('--reference', required=True, help='Reference FASTA')
    parser.add_argument('--gff3', required=True, help='GFF3 gene annotations')
    parser.add_argument('--output', required=True, help='Output TSV path')
    args = parser.parse_args()

    ref_seqs = parse_fasta(args.reference)
    genes = parse_gff3_genes(args.gff3)
    variants = parse_vcf(args.vcf)
    overlaps = parse_intersected(args.intersected)

    results = []
    for var in variants:
        var_id = var['id']

        if var_id not in overlaps:
            # No gene overlap found in intersection — skip this variant
            continue

        gene_name = overlaps[var_id]
        gene = genes[gene_name]

        feature, effect, aa_change = classify_variant(var, gene, ref_seqs)
        if feature is None:
            continue

        results.append({
            'chrom': var['chrom'],
            'pos': var['pos'],
            'ref': var['ref'],
            'alt': var['alt'],
            'gene': gene_name,
            'feature': feature,
            'effect': effect,
            'aa_change': aa_change,
        })

    # Sort by genomic position
    results.sort(key=lambda r: r['pos'])

    with open(args.output, 'w') as f:
        f.write('CHROM\tPOS\tREF\tALT\tGENE\tFEATURE\tEFFECT\tAA_CHANGE\n')
        for r in results:
            f.write(f"{r['chrom']}\t{r['pos']}\t{r['ref']}\t{r['alt']}\t"
                    f"{r['gene']}\t{r['feature']}\t{r['effect']}\t{r['aa_change']}\n")

    print(f"Classified {len(results)} variant effects -> {args.output}")


if __name__ == '__main__':
    main()
