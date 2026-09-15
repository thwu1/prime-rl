#!/usr/bin/env python3
"""Generate synthetic GEO SOFT family file for benchmarking."""
import random
import os
import sys

random.seed(20240115)
os.makedirs("/data", exist_ok=True)

GENES = [
    "TP53", "EGFR", "BRCA1", "BRCA2", "MYC", "KRAS", "PTEN", "RB1",
    "VHL", "APC", "CDH1", "CDKN2A", "PIK3CA", "BRAF", "NRAS",
    "HIF1A", "VEGFA", "CASP3", "BCL2", "BAX", "MDM2", "CCND1",
    "ERBB2", "FOS", "JUN", "MMP9", "MMP2", "TGFB1", "TNF", "IL6",
    "IL8", "CXCL12", "CCL2", "STAT3", "JAK2", "AKT1", "MTOR",
    "NOTCH1", "WNT1", "SHH", "CTNNB1", "SMAD4", "TERT", "IDH1",
    "ALK", "RET", "KIT", "PDGFRA", "FGFR1", "FGFR2", "FGFR3",
    "MET", "ROS1", "MAP2K1", "RAF1", "ARID1A", "KMT2A", "NF1",
    "NF2", "TSC1", "TSC2", "STK11", "KEAP1", "NFE2L2", "BAP1",
    "SETD2", "PBRM1", "KDM5C", "SDHB", "FH", "FLCN", "WT1",
    "PAX8", "CA9", "VEGFC", "PDGFB", "ANGPT2", "FLT1", "KDR",
    "EPAS1", "ARNT", "CUL2", "ELOB", "ELOC", "TCEB1", "GAPDH",
    "ACTB", "B2M", "HPRT1", "TBP", "RPLP0", "GUSB", "HMBS",
    "RPL13A", "SDHA", "YWHAZ", "UBC", "PPIA", "PGK1", "SLC2A1",
    "LDHA", "PKM", "HK2", "ENO1", "ALDOA", "PFKFB3", "PDK1",
    "BNIP3", "BNIP3L", "DDIT4", "ADM", "SLC16A3", "LOX", "LOXL2",
    "COL1A1", "COL3A1", "FN1", "VIM", "CDH2", "SNAI1", "SNAI2",
    "TWIST1", "ZEB1", "ZEB2", "SOX2", "NANOG", "KLF4", "BMI1",
    "ABCG2", "CD44", "ALDH1A1", "LGR5", "AXIN2", "DKK1", "SFRP1",
    "WIF1", "GSK3B", "DVL1", "FZD1", "LRP5", "LRP6", "EZH2",
    "SUZ12", "DNMT1", "DNMT3A", "DNMT3B", "TET1", "TET2", "CDK4",
    "CDK6",
]

NUM_PROBES = 200
NUM_PATIENTS = 20
STAGES = [(1, 6), (2, 6), (3, 5), (4, 3)]
STAGE_ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV"}
OUTLIER_SPEC = {5: "tumor", 17: "normal"}

# Probe-gene mapping
probe_genes = {}
for i in range(NUM_PROBES):
    pid = "PROBE_{:04d}".format(i + 1)
    if i < 10:
        probe_genes[pid] = ""
    elif i < 160:
        probe_genes[pid] = GENES[i - 10]
    else:
        probe_genes[pid] = GENES[random.randint(0, 149)]

# DE probes: 25 randomly chosen from gene-mapped probes
de_indices = sorted(random.sample(range(10, NUM_PROBES), 25))
de_effects = {}
for idx in de_indices:
    pid = "PROBE_{:04d}".format(idx + 1)
    sign = random.choice([-1, 1])
    mag = random.uniform(0.8, 3.0)
    de_effects[pid] = sign * mag

# Base expression (log2 scale)
base_expr = {}
for i in range(NUM_PROBES):
    pid = "PROBE_{:04d}".format(i + 1)
    if i < 10:
        base_expr[pid] = random.uniform(2.0, 4.0)
    else:
        base_expr[pid] = random.uniform(5.0, 12.0)

# Build patient list
patients = []
for stage, count in STAGES:
    for _ in range(count):
        patients.append((len(patients) + 1, stage))

de_set = set(de_indices)

OUT_PATH = "/data/GSE_SYNTH.soft"

# Write SOFT file
with open(OUT_PATH, "w") as f:
    # Platform record
    f.write("^PLATFORM = GPL_SYNTH\n")
    f.write("!Platform_title = Synthetic Human Expression Array HG-200\n")
    f.write("!Platform_technology = in situ oligonucleotide\n")
    f.write("!Platform_distribution = commercial\n")
    f.write("!Platform_organism = Homo sapiens\n")
    f.write("!Platform_manufacturer = Synthetic Genomics Corp\n")
    f.write("!Platform_manufacture_protocol = Standard oligonucleotide synthesis on glass substrate\n")
    f.write("#ID = Probe set identifier\n")
    f.write("#Gene_Symbol = Official HGNC gene symbol\n")
    f.write("#Gene_Title = Full gene name\n")
    f.write("!Platform_table_begin\n")
    f.write("ID\tGene_Symbol\tGene_Title\n")
    for i in range(NUM_PROBES):
        pid = "PROBE_{:04d}".format(i + 1)
        gene = probe_genes[pid]
        title = "{} gene".format(gene) if gene else "Negative control probe"
        f.write("{}\t{}\t{}\n".format(pid, gene, title))
    f.write("!Platform_table_end\n")

    # Series record
    f.write("^SERIES = GSE_SYNTH\n")
    f.write("!Series_title = Gene expression profiling of hepatocellular carcinoma versus matched adjacent normal liver tissue\n")
    f.write("!Series_geo_accession = GSE_SYNTH\n")
    f.write("!Series_summary = High-throughput gene expression analysis comparing hepatocellular carcinoma (HCC) tumor tissue with paired adjacent normal liver tissue across disease stages I-IV to identify novel tumor-specific targets.\n")
    f.write("!Series_overall_design = 20 patients with HCC contributed paired tumor and adjacent normal tissue. Stages I (6 patients), II (6), III (5), IV (3). RNA extracted, hybridized to Synthetic Human Expression Array HG-200.\n")
    f.write("!Series_type = Expression profiling by array\n")
    f.write("!Series_platform_id = GPL_SYNTH\n")
    for pidx in range(NUM_PATIENTS):
        for tidx in range(2):
            snum = pidx * 2 + tidx + 1
            f.write("!Series_sample_id = GSM_SYNTH_{:04d}\n".format(snum))

    # Sample records
    for pidx, (patient_id, stage) in enumerate(patients):
        for tidx, tissue in enumerate(["normal", "tumor"]):
            snum = pidx * 2 + tidx + 1
            sid = "GSM_SYNTH_{:04d}".format(snum)
            is_outlier = (patient_id in OUTLIER_SPEC
                          and OUTLIER_SPEC[patient_id] == tissue)

            f.write("^SAMPLE = {}\n".format(sid))
            f.write("!Sample_title = Patient_{:03d}_{}\n".format(patient_id, tissue))
            f.write("!Sample_geo_accession = {}\n".format(sid))
            f.write("!Sample_status = Public on Jan 15 2024\n")
            f.write("!Sample_type = RNA\n")
            f.write("!Sample_channel_count = 1\n")
            src = ("adjacent normal liver tissue" if tissue == "normal"
                   else "hepatocellular carcinoma tissue")
            f.write("!Sample_source_name_ch1 = {}\n".format(src))
            f.write("!Sample_organism_ch1 = Homo sapiens\n")
            f.write("!Sample_characteristics_ch1 = tissue: {}\n".format(tissue))
            f.write("!Sample_characteristics_ch1 = disease stage: stage {}\n".format(
                STAGE_ROMAN[stage]))
            f.write("!Sample_characteristics_ch1 = patient id: {}\n".format(patient_id))
            f.write("!Sample_molecule_ch1 = total RNA\n")
            f.write("!Sample_extract_protocol_ch1 = Total RNA extracted using TRIzol reagent\n")
            f.write("!Sample_label_ch1 = biotin\n")
            f.write("!Sample_label_protocol_ch1 = Standard IVT labeling with biotin-conjugated nucleotides\n")
            f.write("!Sample_hyb_protocol = Hybridized at 45C for 16 hours\n")
            f.write("!Sample_scan_protocol = Scanned on standard array scanner at 570nm\n")
            f.write("!Sample_data_processing = Quantile normalization applied\n")
            f.write("!Sample_platform_id = GPL_SYNTH\n")
            f.write("#ID_REF = Probe set identifier\n")
            f.write("#VALUE = Normalized signal intensity\n")
            f.write("!Sample_table_begin\n")
            f.write("ID_REF\tVALUE\n")

            for pi in range(NUM_PROBES):
                probe_id = "PROBE_{:04d}".format(pi + 1)
                lv = base_expr[probe_id]
                if tissue == "tumor" and pi in de_set:
                    lv += de_effects[probe_id]
                noise = random.gauss(0, 0.4)
                if is_outlier:
                    noise += 2.5
                val = round(2 ** (lv + noise), 2)
                f.write("{}\t{}\n".format(probe_id, val))

            f.write("!Sample_table_end\n")

# Verify
file_size = os.path.getsize(OUT_PATH)
if file_size < 100000:
    print("ERROR: Generated file too small: {} bytes".format(file_size), file=sys.stderr)
    sys.exit(1)
print("Data generation complete: {} ({} bytes)".format(OUT_PATH, file_size))
