#!/usr/bin/env python3

"""
Solution: Genomic sample swap detection and rare variant analysis pipeline.

1. Parse VCF genotypes and compute pairwise KING-robust kinship
2. Compare kinship against pedigree to detect sample swaps
3. Correct the pedigree
4. Find de novo variants in the affected proband
5. Find compound heterozygous variants within gene boundaries
"""

import os
from collections import defaultdict


def parse_vcf(vcf_path):
    """Parse a VCF file and extract per-sample genotypes for each variant."""
    samples = []
    variants = []

    with open(vcf_path) as f:
        for line in f:
            if line.startswith("##"):
                continue
            if line.startswith("#CHROM"):
                parts = line.strip().split("\t")
                samples = parts[9:]
                continue

            parts = line.strip().split("\t")
            chrom = parts[0]
            pos = int(parts[1])
            ref = parts[3]
            alt = parts[4]
            fmt_fields = parts[8].split(":")
            gt_idx = fmt_fields.index("GT")

            genotypes = {}
            for i, sample in enumerate(samples):
                sample_data = parts[9 + i].split(":")
                gt_str = sample_data[gt_idx]
                alleles = gt_str.replace("|", "/").split("/")
                genotypes[sample] = tuple(sorted(int(a) for a in alleles))

            variants.append({
                "chrom": chrom,
                "pos": pos,
                "ref": ref,
                "alt": alt,
                "genotypes": genotypes,
            })

    return samples, variants


def parse_ped(ped_path):
    """Parse a PED/FAM file."""
    entries = []
    with open(ped_path) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.strip().split("\t")
            entries.append({
                "family_id": parts[0],
                "sample_id": parts[1],
                "paternal_id": parts[2],
                "maternal_id": parts[3],
                "sex": int(parts[4]),
                "phenotype": int(parts[5]),
            })
    return entries


def parse_pop_af(af_path):
    """Parse population allele frequency file."""
    af_map = {}
    with open(af_path) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.strip().split("\t")
            key = (parts[0], int(parts[1]))
            af_map[key] = float(parts[4])
    return af_map


def parse_genes(bed_path):
    """Parse gene BED file."""
    genes = []
    with open(bed_path) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.strip().split("\t")
            genes.append({
                "chrom": parts[0],
                "start": int(parts[1]),
                "end": int(parts[2]),
                "name": parts[3],
            })
    return genes


def compute_king_kinship(gts_a, gts_b):
    """Compute KING-robust kinship estimator between two samples."""
    n_het_a = 0
    n_het_b = 0
    n_hethet = 0
    n_ibs0 = 0
    n_ibs2 = 0

    for ga, gb in zip(gts_a, gts_b):
        het_a = (ga == (0, 1))
        het_b = (gb == (0, 1))

        if het_a:
            n_het_a += 1
        if het_b:
            n_het_b += 1
        if het_a and het_b:
            n_hethet += 1

        # IBS0: discordant homozygotes
        if (ga == (0, 0) and gb == (1, 1)) or (ga == (1, 1) and gb == (0, 0)):
            n_ibs0 += 1

        # IBS2: identical genotypes
        if ga == gb:
            n_ibs2 += 1

    min_het = min(n_het_a, n_het_b)
    if min_het == 0:
        kinship = 0.0
    else:
        kinship = (n_hethet - 2 * n_ibs0) / (2.0 * min_het)

    return n_ibs0, n_ibs2, n_hethet, round(kinship, 6)


def find_variant_gene(chrom, pos, genes):
    """Find which gene a variant falls into (BED is 0-based start, exclusive end)."""
    # VCF pos is 1-based, BED is 0-based start
    pos_0based = pos - 1
    for gene in genes:
        if gene["chrom"] == chrom and gene["start"] <= pos_0based < gene["end"]:
            return gene["name"]
    return None


def main():
    # Parse input files
    samples, variants = parse_vcf("/app/cohort.vcf")
    ped_entries = parse_ped("/app/pedigree.ped")
    pop_af = parse_pop_af("/app/population_af.tsv")
    genes = parse_genes("/app/genes.bed")

    os.makedirs("/app/results", exist_ok=True)

    # Build per-sample genotype vectors
    sample_gts = {s: [v["genotypes"][s] for v in variants] for s in samples}

    # ===== Step 1: Compute pairwise kinship =====
    kinship_map = {}
    kinship_rows = []

    for i in range(len(samples)):
        for j in range(i + 1, len(samples)):
            sa, sb = sorted([samples[i], samples[j]])
            ibs0, ibs2, shared_hets, kinship = compute_king_kinship(
                sample_gts[sa], sample_gts[sb]
            )
            kinship_map[(sa, sb)] = kinship
            kinship_rows.append((sa, sb, ibs0, ibs2, shared_hets, kinship))

    with open("/app/results/kinship.tsv", "w") as f:
        f.write("sample_1\tsample_2\tibs0\tibs2\tshared_hets\tkinship\n")
        for sa, sb, ibs0, ibs2, sh, k in kinship_rows:
            f.write("{}\t{}\t{}\t{}\t{}\t{}\n".format(sa, sb, ibs0, ibs2, sh, k))

    # Helper to look up kinship
    def get_kinship(a, b):
        pair = tuple(sorted([a, b]))
        return kinship_map.get(pair, 0.0)

    # ===== Step 2: Detect sample swaps =====
    # Find children (those with non-zero parental IDs)
    children_info = []
    for entry in ped_entries:
        if entry["paternal_id"] != "0" and entry["maternal_id"] != "0":
            children_info.append(entry)

    # Check if labeled parents have expected kinship (~0.25) with children
    wrong_mothers = {}
    for child_entry in children_info:
        child = child_entry["sample_id"]
        father = child_entry["paternal_id"]
        mother = child_entry["maternal_id"]

        k_father = get_kinship(child, father)
        k_mother = get_kinship(child, mother)

        # Parent-child should have kinship > 0.177 and IBS0 = 0
        if k_mother < 0.10:
            wrong_mothers[child] = mother

    # For each child with wrong mother, find the real mother
    # The real mother should have kinship ~0.25 with the child and IBS0 = 0
    all_female_founders = [
        e["sample_id"]
        for e in ped_entries
        if e["sex"] == 2 and e["paternal_id"] == "0"
    ]

    real_mothers = {}
    swapped = set()
    for child, wrong_mom in wrong_mothers.items():
        for candidate in all_female_founders:
            if candidate == wrong_mom:
                continue
            pair = tuple(sorted([child, candidate]))
            k = kinship_map.get(pair, 0.0)
            # Also check IBS0 for parent-child relationship
            ibs0_val = None
            for row in kinship_rows:
                if (row[0], row[1]) == pair:
                    ibs0_val = row[2]
                    break
            if k > 0.177 and ibs0_val == 0:
                real_mothers[child] = candidate
                swapped.add(wrong_mom)
                swapped.add(candidate)
                break

    swap_list = sorted(swapped)
    with open("/app/results/swapped_samples.txt", "w") as f:
        f.write(" ".join(swap_list) + "\n")

    # ===== Step 3: Write corrected pedigree =====
    # Build the swap mapping
    swap_mapping = {}
    if len(swap_list) == 2:
        swap_mapping[swap_list[0]] = swap_list[1]
        swap_mapping[swap_list[1]] = swap_list[0]

    with open("/app/results/corrected.ped", "w") as f:
        f.write("#family_id\tsample_id\tpaternal_id\tmaternal_id\tsex\tphenotype\n")

        # Determine which family each mother should belong to
        # by looking at which child they are the real mother of
        mother_family = {}
        for child_entry in children_info:
            child = child_entry["sample_id"]
            if child in real_mothers:
                mother_family[real_mothers[child]] = child_entry["family_id"]
            else:
                mother_family[child_entry["maternal_id"]] = child_entry["family_id"]

        for entry in ped_entries:
            sample = entry["sample_id"]
            family = entry["family_id"]
            paternal = entry["paternal_id"]
            maternal = entry["maternal_id"]

            # Fix maternal ID for children
            if sample in real_mothers:
                maternal = real_mothers[sample]

            # Fix family ID for swapped mothers
            if sample in swap_mapping and entry["paternal_id"] == "0":
                if sample in mother_family:
                    family = mother_family[sample]

            f.write("{}\t{}\t{}\t{}\t{}\t{}\n".format(
                family, sample, paternal, maternal,
                entry["sex"], entry["phenotype"]
            ))

    # ===== Step 4: Find de novo variants =====
    # Identify the proband (phenotype=2)
    proband = None
    for entry in ped_entries:
        if entry["phenotype"] == 2:
            proband = entry["sample_id"]
            break

    # Get the correct parents from the corrected pedigree
    proband_father = None
    proband_mother = None
    for entry in ped_entries:
        if entry["sample_id"] == proband:
            proband_father = entry["paternal_id"]
            # Use corrected mother
            proband_mother = real_mothers.get(proband, entry["maternal_id"])
            break

    denovo_variants = []
    for v in variants:
        gt_child = v["genotypes"][proband]
        gt_father = v["genotypes"][proband_father]
        gt_mother = v["genotypes"][proband_mother]
        af = pop_af.get((v["chrom"], v["pos"]), 1.0)

        if (
            gt_child == (0, 1)
            and gt_father == (0, 0)
            and gt_mother == (0, 0)
            and af < 0.01
        ):
            denovo_variants.append((v["chrom"], v["pos"], v["ref"], v["alt"]))

    with open("/app/results/denovo.tsv", "w") as f:
        f.write("chrom\tpos\tref\talt\n")
        for chrom, pos, ref, alt in denovo_variants:
            f.write("{}\t{}\t{}\t{}\n".format(chrom, pos, ref, alt))

    # ===== Step 5: Find compound heterozygous variants =====
    # Collect rare het variants in the proband grouped by gene
    gene_hets = defaultdict(list)

    for v in variants:
        gt_child = v["genotypes"][proband]
        if gt_child != (0, 1):
            continue

        af = pop_af.get((v["chrom"], v["pos"]), 1.0)
        if af >= 0.01:
            continue

        gene = find_variant_gene(v["chrom"], v["pos"], genes)
        if gene is None:
            continue

        gt_father = v["genotypes"][proband_father]
        gt_mother = v["genotypes"][proband_mother]

        # Determine parent of origin
        from_father = gt_father == (0, 1) and gt_mother == (0, 0)
        from_mother = gt_father == (0, 0) and gt_mother == (0, 1)

        if from_father or from_mother:
            origin = "father" if from_father else "mother"
            gene_hets[gene].append({
                "chrom": v["chrom"],
                "pos": v["pos"],
                "origin": origin,
            })

    compound_hets = []
    for gene, hets in gene_hets.items():
        from_father = [h for h in hets if h["origin"] == "father"]
        from_mother = [h for h in hets if h["origin"] == "mother"]

        # Compound het requires at least one from each parent
        for f_var in from_father:
            for m_var in from_mother:
                c1 = f_var["chrom"]
                p1 = f_var["pos"]
                c2 = m_var["chrom"]
                p2 = m_var["pos"]
                # Normalize order
                if (c1, p1) > (c2, p2):
                    c1, p1, c2, p2 = c2, p2, c1, p1
                compound_hets.append((gene, c1, p1, c2, p2))

    with open("/app/results/compound_hets.tsv", "w") as f:
        f.write("gene\tchrom1\tpos1\tchrom2\tpos2\n")
        for gene, c1, p1, c2, p2 in compound_hets:
            f.write("{}\t{}\t{}\t{}\t{}\n".format(gene, c1, p1, c2, p2))

    print("Pipeline complete. Results written to /app/results/")


if __name__ == "__main__":
    main()
