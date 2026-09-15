#!/usr/bin/env python3

"""
Kinship analysis, sample swap detection, pedigree correction, and de novo calling.
Reads genotype matrix extracted by bcftools query.
Writes proband rare het BED for downstream bedtools intersect.
"""

import os


def parse_gt(gt_str):
    """Parse genotype string to sorted allele tuple."""
    alleles = gt_str.replace("|", "/").split("/")
    return tuple(sorted(int(a) for a in alleles))


def load_samples():
    with open("/tmp/work/samples.txt") as f:
        return [line.strip() for line in f if line.strip()]


def load_genotypes(samples):
    """Parse bcftools query output into variant records."""
    variants = []
    with open("/tmp/work/gt_matrix.tsv") as f:
        for line in f:
            parts = line.strip().split("\t")
            chrom, pos, ref, alt = parts[0], int(parts[1]), parts[2], parts[3]
            gts = {}
            for i, s in enumerate(samples):
                gts[s] = parse_gt(parts[4 + i])
            variants.append({
                "chrom": chrom, "pos": pos, "ref": ref, "alt": alt,
                "genotypes": gts,
            })
    return variants


def load_ped(path):
    entries = []
    with open(path) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.strip().split("\t")
            entries.append({
                "family_id": parts[0], "sample_id": parts[1],
                "paternal_id": parts[2], "maternal_id": parts[3],
                "sex": int(parts[4]), "phenotype": int(parts[5]),
            })
    return entries


def load_pop_af(path):
    af = {}
    with open(path) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.strip().split("\t")
            af[(parts[0], int(parts[1]))] = float(parts[4])
    return af


def king_kinship(gts_a, gts_b):
    """Compute KING-robust kinship estimator between two samples."""
    n_het_a = n_het_b = n_hethet = n_ibs0 = n_ibs2 = 0
    for ga, gb in zip(gts_a, gts_b):
        ha = (ga == (0, 1))
        hb = (gb == (0, 1))
        if ha:
            n_het_a += 1
        if hb:
            n_het_b += 1
        if ha and hb:
            n_hethet += 1
        if (ga == (0, 0) and gb == (1, 1)) or (ga == (1, 1) and gb == (0, 0)):
            n_ibs0 += 1
        if ga == gb:
            n_ibs2 += 1
    min_het = min(n_het_a, n_het_b)
    if min_het == 0:
        k = 0.0
    else:
        k = (n_hethet - 2 * n_ibs0) / (2.0 * min_het)
    return n_ibs0, n_ibs2, n_hethet, round(k, 6)


def main():
    samples = load_samples()
    variants = load_genotypes(samples)
    ped = load_ped("/app/pedigree.ped")
    pop_af = load_pop_af("/app/population_af.tsv")

    os.makedirs("/app/results", exist_ok=True)

    sample_gts = {s: [v["genotypes"][s] for v in variants] for s in samples}

    # === Compute pairwise kinship ===
    kinship_map = {}
    kinship_rows = []
    for i in range(len(samples)):
        for j in range(i + 1, len(samples)):
            sa, sb = sorted([samples[i], samples[j]])
            ibs0, ibs2, sh, k = king_kinship(sample_gts[sa], sample_gts[sb])
            kinship_map[(sa, sb)] = k
            kinship_rows.append((sa, sb, ibs0, ibs2, sh, k))

    with open("/app/results/kinship.tsv", "w") as f:
        f.write("sample_1\tsample_2\tibs0\tibs2\tshared_hets\tkinship\n")
        for sa, sb, ibs0, ibs2, sh, k in kinship_rows:
            f.write("{}\t{}\t{}\t{}\t{}\t{}\n".format(sa, sb, ibs0, ibs2, sh, k))

    # === Detect sample swaps ===
    def get_k(a, b):
        return kinship_map.get(tuple(sorted([a, b])), 0.0)

    children = [e for e in ped if e["paternal_id"] != "0" and e["maternal_id"] != "0"]
    mothers = [e["sample_id"] for e in ped if e["sex"] == 2 and e["paternal_id"] == "0"]

    wrong = {}
    for c in children:
        if get_k(c["sample_id"], c["maternal_id"]) < 0.10:
            wrong[c["sample_id"]] = c["maternal_id"]

    real_mothers = {}
    swapped = set()
    for child, wrong_mom in wrong.items():
        for cand in mothers:
            if cand == wrong_mom:
                continue
            pair = tuple(sorted([child, cand]))
            k = kinship_map.get(pair, 0.0)
            ibs0_val = next(
                (r[2] for r in kinship_rows if (r[0], r[1]) == pair), None
            )
            if k > 0.177 and ibs0_val == 0:
                real_mothers[child] = cand
                swapped.update([wrong_mom, cand])
                break

    swap_list = sorted(swapped)
    with open("/app/results/swapped_samples.txt", "w") as f:
        f.write(" ".join(swap_list) + "\n")

    # === Correct pedigree ===
    swap_map = {}
    if len(swap_list) == 2:
        swap_map[swap_list[0]] = swap_list[1]
        swap_map[swap_list[1]] = swap_list[0]

    mother_fam = {}
    for c in children:
        child_id = c["sample_id"]
        if child_id in real_mothers:
            mother_fam[real_mothers[child_id]] = c["family_id"]
        else:
            mother_fam[c["maternal_id"]] = c["family_id"]

    with open("/app/results/corrected.ped", "w") as f:
        f.write("#family_id\tsample_id\tpaternal_id\tmaternal_id\tsex\tphenotype\n")
        for e in ped:
            fam = e["family_id"]
            mat = e["maternal_id"]
            if e["sample_id"] in real_mothers:
                mat = real_mothers[e["sample_id"]]
            if e["sample_id"] in swap_map and e["paternal_id"] == "0":
                if e["sample_id"] in mother_fam:
                    fam = mother_fam[e["sample_id"]]
            f.write("{}\t{}\t{}\t{}\t{}\t{}\n".format(
                fam, e["sample_id"], e["paternal_id"], mat,
                e["sex"], e["phenotype"]
            ))

    # === Identify proband and correct parents ===
    proband = next(e["sample_id"] for e in ped if e["phenotype"] == 2)
    proband_entry = next(e for e in ped if e["sample_id"] == proband)
    father = proband_entry["paternal_id"]
    mother = real_mothers.get(proband, proband_entry["maternal_id"])

    # === De novo variant calling ===
    denovo = []
    for v in variants:
        gc = v["genotypes"][proband]
        gf = v["genotypes"][father]
        gm = v["genotypes"][mother]
        af = pop_af.get((v["chrom"], v["pos"]), 1.0)
        if gc == (0, 1) and gf == (0, 0) and gm == (0, 0) and af < 0.01:
            denovo.append((v["chrom"], v["pos"], v["ref"], v["alt"]))

    with open("/app/results/denovo.tsv", "w") as f:
        f.write("chrom\tpos\tref\talt\n")
        for c, p, r, a in denovo:
            f.write("{}\t{}\t{}\t{}\n".format(c, p, r, a))

    # === Write BED of proband rare hets with parent-of-origin for bedtools ===
    with open("/tmp/work/proband_rare_hets.bed", "w") as f:
        for v in variants:
            gc = v["genotypes"][proband]
            if gc != (0, 1):
                continue
            af = pop_af.get((v["chrom"], v["pos"]), 1.0)
            if af >= 0.01:
                continue
            gf = v["genotypes"][father]
            gm = v["genotypes"][mother]
            from_father = (gf == (0, 1) and gm == (0, 0))
            from_mother = (gf == (0, 0) and gm == (0, 1))
            if from_father:
                origin = "father"
            elif from_mother:
                origin = "mother"
            else:
                continue
            # BED: 0-based start, 1-based end
            f.write("{}\t{}\t{}\t{}\t{}\n".format(
                v["chrom"], v["pos"] - 1, v["pos"], v["pos"], origin
            ))


if __name__ == "__main__":
    main()
