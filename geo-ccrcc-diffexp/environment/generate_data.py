#!/usr/bin/env python3
"""Generate synthetic GEO SOFT file and GPL570 annotation for ccRCC DE analysis task."""
import random
import math
import os

random.seed(42)

DATA_DIR = "/opt/geo_data"
os.makedirs(DATA_DIR, exist_ok=True)

# Gene definitions: (symbol, [probe_ids], log2fc_tumor_vs_normal, base_normal_expr)
GENES = [
    ("CA9", ["205199_at", "205200_at"], 4.5, 200),
    ("VHL", ["203454_s_at", "203453_at"], -2.1, 3000),
    ("VEGFA", ["210512_s_at", "211527_x_at"], 3.2, 400),
    ("HIF1A", ["200989_at", "200988_s_at"], 2.0, 800),
    ("EGLN3", ["219622_at", "219623_at"], 2.8, 300),
    ("PAX8", ["207136_at", "207137_at"], -0.5, 2500),
    ("SLC2A1", ["201250_s_at", "201249_at"], 2.5, 500),
    ("NDUFA4L2", ["228142_at", "228143_at"], 5.0, 150),
    ("ANGPTL4", ["221009_s_at", "223333_s_at"], 3.5, 350),
    ("BHLHE40", ["201170_s_at", "201169_s_at"], 2.2, 600),
    ("PGK1", ["200738_s_at", "200737_at"], 1.8, 1200),
    ("ENO2", ["201313_at", "201312_s_at"], 1.5, 900),
    ("ALDOB", ["211357_s_at", "217238_s_at"], -3.8, 5000),
    ("KRT19", ["201650_at", "201651_s_at"], 0.8, 1800),
    ("PCSK6", ["1552263_at", "1552264_a_at"], 0.1, 700),
    ("DDR1", ["1007_s_at"], 0.3, 2200),
    ("RFC2", ["1053_at"], 0.5, 650),
    ("HSPA6", ["117_at"], 1.2, 300),
    ("GUCA1A", ["1255_g_at"], -1.5, 1500),
    ("UBA7", ["1294_at"], -0.8, 550),
    ("THRA", ["1316_at"], -1.0, 400),
    ("PTPN21", ["1320_at"], 0.2, 800),
    ("CCL5", ["1405_i_at"], 1.8, 350),
    ("CYP2E1", ["1431_at"], -2.5, 4000),
    ("EPHB3", ["1438_at"], -0.4, 600),
    ("ESRRA", ["1487_at"], 0.6, 750),
    ("SCARB1", ["1552256_a_at"], 0.7, 1100),
    ("TTLL3", ["1552258_at"], -0.3, 500),
    ("PDLIM3", ["1552266_at"], -1.2, 900),
    ("TP53", ["201746_at"], -0.2, 1600),
    ("MYC", ["202431_s_at"], 1.4, 450),
    ("EGFR", ["201983_s_at"], 1.0, 550),
    ("AKT1", ["207163_s_at"], 0.8, 1000),
    ("MTOR", ["202116_at"], 0.5, 850),
    ("PIK3CA", ["204369_at"], 0.4, 700),
    ("PTEN", ["204054_at"], -1.5, 1800),
    ("BRCA1", ["204531_s_at"], -0.6, 400),
    ("MAPK1", ["212271_at"], 0.3, 1200),
    ("JAK2", ["205841_at"], 1.1, 500),
    ("STAT3", ["208991_at"], 0.9, 900),
    ("SRC", ["205145_s_at"], 0.7, 600),
    ("KDR", ["203934_at"], 2.0, 250),
    ("PDGFRA", ["203131_at"], -0.8, 700),
    ("MET", ["203510_at"], 2.3, 400),
    ("FLT1", ["204406_at"], 1.6, 350),
    ("ERBB2", ["216836_s_at"], 0.5, 1300),
    ("CDH1", ["201131_s_at"], -1.8, 2000),
    ("VIM", ["201426_s_at"], 2.4, 500),
    ("SNAI1", ["219967_at"], 1.3, 300),
    ("ZEB1", ["212764_at"], 1.7, 400),
    ("TGFB1", ["203085_s_at"], 1.0, 800),
    ("IL6", ["205207_at"], 2.0, 200),
    ("TNF", ["207113_s_at"], 0.3, 350),
    ("CXCL8", ["202859_x_at"], 2.5, 250),
    ("MMP9", ["203936_s_at"], 1.9, 300),
    ("MMP2", ["201069_at"], 1.2, 600),
    ("TIMP1", ["201666_at"], 1.5, 800),
    ("CASP3", ["202763_at"], -0.4, 1000),
    ("BCL2", ["203685_at"], -1.0, 1200),
    ("BAX", ["208478_s_at"], 0.6, 900),
    ("GAPDH", ["217398_x_at"], 0.05, 8000),
    ("ACTB", ["200801_x_at"], 0.02, 12000),
    ("TUBB", ["212320_at"], 0.08, 5000),
    ("CDKN1A", ["202284_s_at"], 1.4, 600),
    ("RB1", ["203132_at"], -0.7, 1100),
]

UNMAPPED = [
    "AFFX-HUMISGF3A/M97935_3_at",
    "AFFX-HUMRGE/M10098_3_at",
    "AFFX-HSAC07/X00351_5_at",
    "AFFX-M27830_3_at",
    "AFFX-BioB-3_at",
]

# Stage-specific multipliers applied to tumor samples
STAGE_EFFECTS = {
    "CA9": {1: 1.0, 2: 1.4, 3: 2.0, 4: 3.0},
    "VEGFA": {1: 1.0, 2: 1.2, 3: 1.5, 4: 2.0},
    "VHL": {1: 1.0, 2: 0.9, 3: 0.7, 4: 0.5},
}

SAMPLES = [
    {"id": "GSM1300062", "title": "102T", "tissue": "clear cell renal cell carcinoma",
     "stage": "stage 1", "type": "tumor", "patient": "PT1001", "batch": "A"},
    {"id": "GSM1300063", "title": "106T", "tissue": "clear cell renal cell carcinoma",
     "stage": "stage 1", "type": "tumor", "patient": "PT1002", "batch": "A"},
    {"id": "GSM1300064", "title": "112T", "tissue": "clear cell renal cell carcinoma",
     "stage": "stage 1", "type": "tumor", "patient": "PT1003", "batch": "A"},
    {"id": "GSM1300065", "title": "203T", "tissue": "clear cell renal cell carcinoma",
     "stage": "stage 2", "type": "tumor", "patient": "PT2001", "batch": "A"},
    {"id": "GSM1300066", "title": "207T", "tissue": "clear cell renal cell carcinoma",
     "stage": "stage 2", "type": "tumor", "patient": "PT2002", "batch": "B"},
    {"id": "GSM1300067", "title": "211T", "tissue": "clear cell renal cell carcinoma",
     "stage": "stage 2", "type": "tumor", "patient": "PT2003", "batch": "B"},
    {"id": "GSM1300068", "title": "304T", "tissue": "clear cell renal cell carcinoma",
     "stage": "stage 3", "type": "tumor", "patient": "PT3001", "batch": "B"},
    {"id": "GSM1300069", "title": "308T", "tissue": "clear cell renal cell carcinoma",
     "stage": "stage 3", "type": "tumor", "patient": "PT3002", "batch": "B"},
    {"id": "GSM1300070", "title": "315T", "tissue": "clear cell renal cell carcinoma",
     "stage": "stage 3", "type": "tumor", "patient": "PT3003", "batch": "B"},
    {"id": "GSM1300071", "title": "401T", "tissue": "clear cell renal cell carcinoma",
     "stage": "stage 4", "type": "tumor", "patient": "PT4001", "batch": "A"},
    {"id": "GSM1300072", "title": "405T", "tissue": "clear cell renal cell carcinoma",
     "stage": "stage 4", "type": "tumor", "patient": "PT4002", "batch": "A"},
    {"id": "GSM1300073", "title": "410T", "tissue": "clear cell renal cell carcinoma",
     "stage": "stage 4", "type": "tumor", "patient": "PT4003", "batch": "B"},
    {"id": "GSM1300074", "title": "102N", "tissue": "matched normal kidney",
     "stage": "N/A", "type": "normal", "patient": "PT1001", "batch": "A"},
    {"id": "GSM1300075", "title": "106N", "tissue": "matched normal kidney",
     "stage": "N/A", "type": "normal", "patient": "PT1002", "batch": "A"},
    {"id": "GSM1300076", "title": "112N", "tissue": "matched normal kidney",
     "stage": "N/A", "type": "normal", "patient": "PT1003", "batch": "A"},
    {"id": "GSM1300077", "title": "203N", "tissue": "matched normal kidney",
     "stage": "N/A", "type": "normal", "patient": "PT2001", "batch": "A"},
    {"id": "GSM1300078", "title": "207N", "tissue": "matched normal kidney",
     "stage": "N/A", "type": "normal", "patient": "PT2002", "batch": "B"},
    {"id": "GSM1300079", "title": "211N", "tissue": "matched normal kidney",
     "stage": "N/A", "type": "normal", "patient": "PT2003", "batch": "B"},
    {"id": "GSM1300080", "title": "304N", "tissue": "matched normal kidney",
     "stage": "N/A", "type": "normal", "patient": "PT3001", "batch": "B"},
    {"id": "GSM1300081", "title": "308N", "tissue": "matched normal kidney",
     "stage": "N/A", "type": "normal", "patient": "PT3002", "batch": "B"},
    {"id": "GSM1300082", "title": "315N", "tissue": "matched normal kidney",
     "stage": "N/A", "type": "normal", "patient": "PT3003", "batch": "B"},
    {"id": "GSM1300083", "title": "401N", "tissue": "matched normal kidney",
     "stage": "N/A", "type": "normal", "patient": "PT4001", "batch": "A"},
    {"id": "GSM1300084", "title": "405N", "tissue": "matched normal kidney",
     "stage": "N/A", "type": "normal", "patient": "PT4002", "batch": "A"},
    {"id": "GSM1300085", "title": "410N", "tissue": "matched normal kidney",
     "stage": "N/A", "type": "normal", "patient": "PT4003", "batch": "B"},
]

GENE_TITLES = {
    "CA9": "carbonic anhydrase 9",
    "VHL": "von Hippel-Lindau tumor suppressor",
    "VEGFA": "vascular endothelial growth factor A",
    "HIF1A": "hypoxia inducible factor 1 subunit alpha",
    "EGLN3": "egl-9 family hypoxia inducible factor 3",
    "PAX8": "paired box 8",
    "SLC2A1": "solute carrier family 2 member 1",
    "NDUFA4L2": "NDUFA4 mitochondrial complex associated like 2",
    "ANGPTL4": "angiopoietin like 4",
    "BHLHE40": "basic helix-loop-helix family member e40",
    "PGK1": "phosphoglycerate kinase 1",
    "ENO2": "enolase 2",
    "ALDOB": "aldolase fructose-bisphosphate B",
    "KRT19": "keratin 19",
    "PCSK6": "proprotein convertase subtilisin/kexin type 6",
    "DDR1": "discoidin domain receptor tyrosine kinase 1",
    "RFC2": "replication factor C subunit 2",
    "HSPA6": "heat shock protein family A member 6",
    "GUCA1A": "guanylate cyclase activator 1A",
    "UBA7": "ubiquitin like modifier activating enzyme 7",
    "THRA": "thyroid hormone receptor alpha",
    "PTPN21": "protein tyrosine phosphatase non-receptor type 21",
    "CCL5": "C-C motif chemokine ligand 5",
    "CYP2E1": "cytochrome P450 family 2 subfamily E member 1",
    "EPHB3": "EPH receptor B3",
    "ESRRA": "estrogen related receptor alpha",
    "SCARB1": "scavenger receptor class B member 1",
    "TTLL3": "tubulin tyrosine ligase like 3",
    "PDLIM3": "PDZ and LIM domain 3",
    "TP53": "tumor protein p53",
    "MYC": "MYC proto-oncogene",
    "EGFR": "epidermal growth factor receptor",
    "AKT1": "AKT serine/threonine kinase 1",
    "MTOR": "mechanistic target of rapamycin kinase",
    "PIK3CA": "phosphatidylinositol-4,5-bisphosphate 3-kinase catalytic subunit alpha",
    "PTEN": "phosphatase and tensin homolog",
    "BRCA1": "BRCA1 DNA repair associated",
    "MAPK1": "mitogen-activated protein kinase 1",
    "JAK2": "Janus kinase 2",
    "STAT3": "signal transducer and activator of transcription 3",
    "SRC": "SRC proto-oncogene",
    "KDR": "kinase insert domain receptor",
    "PDGFRA": "platelet derived growth factor receptor alpha",
    "MET": "MET proto-oncogene",
    "FLT1": "fms related receptor tyrosine kinase 1",
    "ERBB2": "erb-b2 receptor tyrosine kinase 2",
    "CDH1": "cadherin 1",
    "VIM": "vimentin",
    "SNAI1": "snail family transcriptional repressor 1",
    "ZEB1": "zinc finger E-box binding homeobox 1",
    "TGFB1": "transforming growth factor beta 1",
    "IL6": "interleukin 6",
    "TNF": "tumor necrosis factor",
    "CXCL8": "C-X-C motif chemokine ligand 8",
    "MMP9": "matrix metallopeptidase 9",
    "MMP2": "matrix metallopeptidase 2",
    "TIMP1": "TIMP metallopeptidase inhibitor 1",
    "CASP3": "caspase 3",
    "BCL2": "BCL2 apoptosis regulator",
    "BAX": "BCL2 associated X",
    "GAPDH": "glyceraldehyde-3-phosphate dehydrogenase",
    "ACTB": "actin beta",
    "TUBB": "tubulin beta class I",
    "CDKN1A": "cyclin dependent kinase inhibitor 1A",
    "RB1": "RB transcriptional corepressor 1",
}

ENTREZ_IDS = {
    "CA9": "768", "VHL": "7428", "VEGFA": "7422", "HIF1A": "3091",
    "EGLN3": "112399", "PAX8": "7849", "SLC2A1": "6513", "NDUFA4L2": "56901",
    "ANGPTL4": "51129", "BHLHE40": "8553", "PGK1": "5230", "ENO2": "2026",
    "ALDOB": "229", "KRT19": "3880", "PCSK6": "5046", "DDR1": "780",
    "RFC2": "5982", "HSPA6": "3310", "GUCA1A": "2978", "UBA7": "7318",
    "THRA": "7067", "PTPN21": "11099", "CCL5": "6352", "CYP2E1": "1571",
    "EPHB3": "2049", "ESRRA": "2101", "SCARB1": "949", "TTLL3": "26140",
    "PDLIM3": "27295", "TP53": "7157", "MYC": "4609", "EGFR": "1956",
    "AKT1": "207", "MTOR": "2475", "PIK3CA": "5290", "PTEN": "5728",
    "BRCA1": "672", "MAPK1": "5594", "JAK2": "3717", "STAT3": "6774",
    "SRC": "6714", "KDR": "3791", "PDGFRA": "5156", "MET": "4233",
    "FLT1": "2321", "ERBB2": "2064", "CDH1": "999", "VIM": "7431",
    "SNAI1": "6615", "ZEB1": "6935", "TGFB1": "7040", "IL6": "3569",
    "TNF": "7124", "CXCL8": "3576", "MMP9": "4318", "MMP2": "4313",
    "TIMP1": "7076", "CASP3": "836", "BCL2": "596", "BAX": "581",
    "GAPDH": "2597", "ACTB": "60", "TUBB": "203068", "CDKN1A": "1026",
    "RB1": "5925",
}

# Build ordered probe list
all_probes = []
for _, probes, _, _ in GENES:
    all_probes.extend(probes)
all_probes.extend(UNMAPPED)

# Generate expression data
data = {}
for sample in SAMPLES:
    sid = sample["id"]
    is_tumor = sample["type"] == "tumor"
    stage = int(sample["stage"].split()[-1]) if is_tumor else 0

    vals = {}
    for gene, probes, fc, base in GENES:
        for pi, probe in enumerate(probes):
            if len(probes) > 1:
                probe_base = base * (0.85 + 0.3 * pi / (len(probes) - 1))
            else:
                probe_base = float(base)

            if is_tumor:
                tumor_fc = 2.0 ** fc
                stage_mult = STAGE_EFFECTS.get(gene, {}).get(stage, 1.0)
                expected = probe_base * tumor_fc * stage_mult
            else:
                expected = probe_base

            noise = random.gauss(0, expected * 0.12)
            vals[probe] = round(max(1.0, expected + noise), 4)

    for p in UNMAPPED:
        vals[p] = round(random.uniform(50, 500), 4)

    data[sid] = vals

# Write SOFT file
soft_path = os.path.join(DATA_DIR, "GSE53757_family.soft")
with open(soft_path, "w") as f:
    # Series header
    f.write("^SERIES = GSE53757\n")
    f.write("!Series_title = Gene array analysis of clear cell renal cell carcinoma tissue versus matched normal kidney tissue\n")
    f.write("!Series_geo_accession = GSE53757\n")
    f.write("!Series_status = Public on Jan 03 2014\n")
    f.write("!Series_submission_date = Jan 02 2014\n")
    f.write("!Series_last_update_date = Mar 25 2019\n")
    f.write("!Series_pubmed_id = 24962026\n")
    f.write("!Series_summary = Currently there is a lack of effective therapies which result in long-term durable response for patients presenting with advanced and metastatic clear cell renal cell carcinoma (ccRCC). This is due in part to a lack of molecular factors which can be targeted pharmacologically. In order to identify novel tumor-specific targets, we performed high throughput gene array analysis screening numerous patient ccRCC tumor tissues across all stages of disease, and compared their gene expression levels to matched normal kidney.\n")
    f.write("!Series_overall_design = Patient tissue samples were sorted into disease stages based on pathology reports. RNA was extracted from flash frozen patient tumor and normal samples. Gene array analysis was performed, and resulting expression levels were compared between normal and tumor samples.\n")
    f.write("!Series_type = Expression profiling by array\n")
    f.write("!Series_contributor = Christina,A,von Roemeling\n")
    f.write("!Series_contributor = John,A,Copland\n")
    for s in SAMPLES:
        f.write("!Series_sample_id = {}\n".format(s["id"]))
    f.write("!Series_platform_id = GPL570\n")
    f.write("!Series_platform_organism = Homo sapiens\n")
    f.write("!Series_platform_taxid = 9606\n")
    f.write("!Series_relation = BioProject: https://www.ncbi.nlm.nih.gov/bioproject/PRJNA232816\n")

    # Sample entries
    for sample in SAMPLES:
        sid = sample["id"]
        f.write("^SAMPLE = {}\n".format(sid))
        f.write("!Sample_title = {}\n".format(sample["title"]))
        f.write("!Sample_geo_accession = {}\n".format(sid))
        f.write("!Sample_status = Public on Jan 03 2014\n")
        f.write("!Sample_type = RNA\n")
        f.write("!Sample_channel_count = 1\n")
        if sample["type"] == "tumor":
            f.write("!Sample_source_name_ch1 = {} ccRCC\n".format(sample["stage"].title()))
        else:
            f.write("!Sample_source_name_ch1 = Normal kidney\n")
        f.write("!Sample_organism_ch1 = Homo sapiens\n")
        f.write("!Sample_taxid_ch1 = 9606\n")
        f.write("!Sample_characteristics_ch1 = tissue: {}\n".format(sample["tissue"]))
        f.write("!Sample_characteristics_ch1 = tumor stage: {}\n".format(sample["stage"]))
        f.write("!Sample_characteristics_ch1 = sample type: {}\n".format(sample["type"]))
        f.write("!Sample_characteristics_ch1 = patient id: {}\n".format(sample["patient"]))
        f.write("!Sample_characteristics_ch1 = batch: {}\n".format(sample["batch"]))
        f.write("!Sample_molecule_ch1 = total RNA\n")
        f.write("!Sample_extract_protocol_ch1 = RNA was extracted from flash frozen patient tissue samples (RCC tissue and matched normal kidney tissue) using TRIzol (Invitrogen) and chloroform (Sigma). All tumor samples are from the primary tumor site.\n")
        f.write("!Sample_label_ch1 = biotin\n")
        f.write("!Sample_label_protocol_ch1 = The RNA products were column-purified (Affymetrix) and then in vitro transcribed to generate biotin-labeled cRNA.\n")
        f.write("!Sample_hyb_protocol = The IVT products were column-purified, fragmented, and hybridized onto Affymetrix U133 Plus 2.0 GeneChips at 45C for 16 h.\n")
        f.write("!Sample_scan_protocol = Arrays were washed, stained with streptavidin-phycoerythrin, then scanned in an Affymetrix GeneChip Scanner 3000.\n")
        f.write("!Sample_data_processing = Raw data was processed by MAS5.0 (Affymetrix) and analyzed using GeneSpring GX10.\n")
        f.write("!Sample_platform_id = GPL570\n")
        f.write("!Sample_series_id = GSE53757\n")
        f.write("!Sample_data_row_count = {}\n".format(len(all_probes)))
        f.write("#ID_REF = \n")
        f.write("#VALUE = MAS5.0 signal intensity\n")
        f.write("!sample_table_begin\n")
        f.write("ID_REF\tVALUE\n")
        for probe in all_probes:
            f.write("{}\t{}\n".format(probe, data[sid][probe]))
        f.write("!sample_table_end\n")

# Write annotation file
annot_path = os.path.join(DATA_DIR, "GPL570_annotation.tsv")
with open(annot_path, "w") as f:
    f.write("ID\tGene Symbol\tGene Title\tENTREZ_GENE_ID\n")
    for gene, probes, _, _ in GENES:
        title = GENE_TITLES.get(gene, "")
        eid = ENTREZ_IDS.get(gene, "")
        for probe in probes:
            f.write("{}\t{}\t{}\t{}\n".format(probe, gene, title, eid))
    for p in UNMAPPED:
        f.write("{}\t---\t---\t---\n".format(p))

print("Generated SOFT file: {} ({} samples, {} probes)".format(
    soft_path, len(SAMPLES), len(all_probes)))
print("Generated annotation: {} ({} mapped + {} unmapped probes)".format(
    annot_path, sum(len(p) for _, p, _, _ in GENES), len(UNMAPPED)))
