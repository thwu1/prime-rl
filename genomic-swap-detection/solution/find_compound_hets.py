#!/usr/bin/env python3

"""
Find compound heterozygous variant pairs from bedtools intersect output.
Reads the gene-mapped variants and groups by gene to find pairs
with one variant inherited from each parent.
"""

from collections import defaultdict


def main():
    gene_variants = defaultdict(list)

    with open("/tmp/work/gene_mapped.tsv") as f:
        for line in f:
            parts = line.strip().split("\t")
            # bedtools intersect -wa -wb output:
            # var_chrom, var_start, var_end, var_pos, origin,
            # gene_chrom, gene_start, gene_end, gene_name
            chrom = parts[0]
            pos = int(parts[3])
            origin = parts[4]
            gene = parts[8]
            gene_variants[gene].append({
                "chrom": chrom, "pos": pos, "origin": origin,
            })

    compound_hets = []
    for gene, vlist in gene_variants.items():
        from_father = [v for v in vlist if v["origin"] == "father"]
        from_mother = [v for v in vlist if v["origin"] == "mother"]
        for fv in from_father:
            for mv in from_mother:
                c1, p1 = fv["chrom"], fv["pos"]
                c2, p2 = mv["chrom"], mv["pos"]
                if (c1, p1) > (c2, p2):
                    c1, p1, c2, p2 = c2, p2, c1, p1
                compound_hets.append((gene, c1, p1, c2, p2))

    with open("/app/results/compound_hets.tsv", "w") as f:
        f.write("gene\tchrom1\tpos1\tchrom2\tpos2\n")
        for gene, c1, p1, c2, p2 in compound_hets:
            f.write("{}\t{}\t{}\t{}\t{}\n".format(gene, c1, p1, c2, p2))


if __name__ == "__main__":
    main()
