#!/usr/bin/env python3
"""Generate synthetic RNA-seq count data stored in a SQLite database.

Creates a realistic gene expression dataset where:
- Treatment samples show a heat shock response (HSP genes up, cell cycle genes down)
- 4 samples have been mislabeled (2 swap pairs between conditions)
- A batch effect partially confounds with condition
- Technical outliers exist in specific genes/samples

Data is stored in a relational SQLite database with normalized tables,
requiring the analyst to explore the schema and extract/pivot data.
"""
import numpy as np
import sqlite3
import os

np.random.seed(20260613)

# ============================================================
# 1. Differentially expressed gene lists
# ============================================================
HEAT_SHOCK_UP = [
    'HSPA1A', 'HSPA1B', 'HSPA6', 'HSPA4L', 'HSP90AA1', 'HSP90AB1',
    'HSPB1', 'HSPB8', 'HSPH1', 'HSPD1', 'HSPE1', 'DNAJA1', 'DNAJA4',
    'DNAJB1', 'DNAJB4', 'DNAJB6', 'BAG3', 'SERPINH1', 'STIP1', 'FKBP4',
    'AHSA1', 'CHORDC1', 'CACYBP', 'TCP1', 'CCT2', 'CCT3', 'CCT4', 'CCT5',
    'CCT7', 'HSPA4'
]

CELL_CYCLE_DOWN = [
    'CDK1', 'CDK2', 'CCNA2', 'CCNB1', 'CCNB2', 'CCNE1', 'CDC20',
    'CDC25A', 'AURKB', 'PLK1', 'BUB1', 'BUB1B', 'MAD2L1', 'CENPE',
    'KIF11', 'TOP2A', 'MKI67', 'PCNA', 'MCM2', 'MCM4'
]

HOUSEKEEPING = [
    'ACTB', 'GAPDH', 'TUBB', 'RPL13A', 'RPS18', 'RPL5', 'RPS3',
    'RPL11', 'RPS14', 'RPL7A', 'EEF1A1', 'EEF2', 'TUBA1B', 'VIM',
    'FLNA', 'LMNA', 'DES', 'KRT18', 'KRT8', 'ENO1', 'PKM', 'LDHA',
    'ALDOA', 'TPI1', 'PGK1', 'PGAM1', 'GPI', 'PFKL', 'HK1', 'HK2',
    'ATP5F1B', 'ATP5F1A', 'ATP5MC1', 'UQCRC1', 'NDUFA1', 'SDHA',
    'CS', 'IDH1', 'MDH1', 'ACO2', 'FH', 'OGDH', 'DLST', 'SUCLG1',
    'SUCLA2', 'PDHB', 'PDHA1', 'SLC25A3', 'SLC25A5', 'VDAC1'
]

# ============================================================
# 2. Pathway annotations (GMT format)
# ============================================================
PATHWAYS = {
    'HEAT_SHOCK_RESPONSE': list(HEAT_SHOCK_UP),
    'CELL_CYCLE_REGULATION': CELL_CYCLE_DOWN + [
        'CDK4', 'CDK6', 'CCND1', 'RB1', 'E2F1',
        'CDKN1A', 'CDKN2A', 'TP53', 'CHEK1', 'CHEK2'
    ],
    'P53_SIGNALING_PATHWAY': [
        'TP53', 'MDM2', 'CDKN1A', 'BAX', 'BBC3', 'PMAIP1',
        'GADD45A', 'GADD45B', 'DDB2', 'SFN', 'SESN1', 'SESN2',
        'TIGAR', 'STEAP3', 'RRM2B'
    ],
    'APOPTOSIS_SIGNALING': [
        'CASP3', 'CASP8', 'CASP9', 'BCL2', 'BCL2L1', 'BAK1',
        'BAX', 'BID', 'CYCS', 'APAF1', 'DIABLO', 'XIAP',
        'BIRC5', 'MCL1', 'BCL2L11'
    ],
    'INFLAMMATORY_RESPONSE': [
        'TNF', 'IL6', 'IL1B', 'CXCL8', 'CCL2', 'CXCL10',
        'NFKB1', 'RELA', 'IKBKB', 'TRAF2', 'MYD88', 'TLR4',
        'IRAK4', 'IRF3', 'STAT3'
    ],
    'OXIDATIVE_STRESS_RESPONSE': [
        'SOD1', 'SOD2', 'CAT', 'GPX1', 'GPX4', 'PRDX1',
        'TXN', 'TXNRD1', 'NQO1', 'HMOX1', 'NFE2L2', 'KEAP1',
        'GSR', 'GCLC', 'GCLM'
    ],
    'DNA_DAMAGE_REPAIR': [
        'BRCA1', 'BRCA2', 'RAD51', 'ATM', 'ATR', 'CHEK1',
        'CHEK2', 'XRCC1', 'PARP1', 'LIG3', 'OGG1', 'MSH2',
        'MLH1', 'XPC', 'ERCC1'
    ],
    'PROTEIN_FOLDING_QC': [
        'HSPA5', 'HSP90B1', 'CANX', 'CALR', 'PDIA3', 'PDIA4',
        'PDIA6', 'ERO1A', 'UGGT1', 'EDEM1', 'DNAJC3', 'SEC61A1',
        'SEC61B', 'SSR1', 'SRP54', 'HSPD1', 'HSPE1'
    ],
    'UNFOLDED_PROTEIN_RESPONSE': [
        'ATF4', 'ATF6', 'XBP1', 'DDIT3', 'ERN1', 'EIF2AK3',
        'HSPA5', 'DNAJC3', 'PPP1R15A', 'EDEM1', 'HERPUD1',
        'SEL1L', 'VCP', 'UBXN4', 'DERL1'
    ],
    'TRANSLATION_INITIATION': [
        'EIF4A1', 'EIF4E', 'EIF4G1', 'EIF2S1', 'EIF2S2', 'EIF2S3',
        'EIF3A', 'EIF5', 'EIF5B', 'ETF1', 'GSPT1', 'RPL3',
        'RPL4', 'RPS2', 'RPS3A'
    ],
    'FERROPTOSIS': [
        'GPX4', 'SLC7A11', 'ACSL4', 'LPCAT3', 'ALOX15',
        'HMOX1', 'FTH1', 'FTL', 'NCOA4', 'IREB2',
        'TFRC', 'SLC3A2', 'GLS2', 'CHAC1', 'PTGS2'
    ],
    'AUTOPHAGY': [
        'BECN1', 'ATG5', 'ATG7', 'ATG12', 'ATG16L1',
        'MAP1LC3B', 'SQSTM1', 'ULK1', 'PIK3C3', 'AMBRA1',
        'ATG3', 'ATG4B', 'GABARAP', 'LAMP1', 'LAMP2'
    ],
}

# ============================================================
# 3. Construct full gene list
# ============================================================
existing = set(HEAT_SHOCK_UP) | set(CELL_CYCLE_DOWN) | set(HOUSEKEEPING)
pathway_neutral = sorted(
    {g for genes in PATHWAYS.values() for g in genes} - existing
)
n_bg = 2000 - len(HEAT_SHOCK_UP) - len(CELL_CYCLE_DOWN) - len(HOUSEKEEPING) - len(pathway_neutral)
BACKGROUND = [f'BGENE_{i:04d}' for i in range(1, n_bg + 1)]

ALL_GENES = HEAT_SHOCK_UP + CELL_CYCLE_DOWN + HOUSEKEEPING + pathway_neutral + BACKGROUND
N_GENES = len(ALL_GENES)

assert len(ALL_GENES) == len(set(ALL_GENES)), "Duplicate genes detected"

HS_END = len(HEAT_SHOCK_UP)
CC_END = HS_END + len(CELL_CYCLE_DOWN)

# ============================================================
# 4. Sample setup
# ============================================================
N_SAMPLES = 24
SAMPLE_NAMES = [f'Sample_{i:02d}' for i in range(1, N_SAMPLES + 1)]

TRUE_LABELS = {f'Sample_{i:02d}': 'Control' if i <= 12 else 'Treatment'
               for i in range(1, 25)}

METADATA_LABELS = dict(TRUE_LABELS)
METADATA_LABELS['Sample_04'] = 'Treatment'
METADATA_LABELS['Sample_09'] = 'Treatment'
METADATA_LABELS['Sample_17'] = 'Control'
METADATA_LABELS['Sample_21'] = 'Control'

# ============================================================
# 5. Generate count data
# ============================================================
base_means = np.abs(np.random.lognormal(mean=4.5, sigma=1.8, size=N_GENES))
base_means = np.clip(base_means, 10, 30000)
dispersions = np.random.uniform(0.05, 0.4, size=N_GENES)

# Treatment fold-changes: strong enough to dominate over batch effect
hs_up_fcs = np.random.uniform(4.0, 10.0, size=len(HEAT_SHOCK_UP))
cc_down_fcs = np.random.uniform(0.1, 0.3, size=len(CELL_CYCLE_DOWN))

counts = np.zeros((N_GENES, N_SAMPLES), dtype=int)
for j in range(N_SAMPLES):
    sname = SAMPLE_NAMES[j]
    is_treat = TRUE_LABELS[sname] == 'Treatment'
    # Moderate batch effect (global scaling, confounded with condition)
    batch_f = 1.08 if int(sname.split('_')[1]) > 12 else 1.0
    size_f = np.random.lognormal(0, 0.15)

    for i in range(N_GENES):
        mu = base_means[i] * size_f * batch_f
        if is_treat and i < HS_END:
            mu *= hs_up_fcs[i]
        elif is_treat and HS_END <= i < CC_END:
            mu *= cc_down_fcs[i - HS_END]

        alpha = dispersions[i]
        n_param = 1.0 / alpha
        p_param = n_param / (n_param + mu)
        p_param = np.clip(p_param, 0.0001, 0.9999)
        counts[i, j] = np.random.negative_binomial(max(1, round(n_param)), p_param)

# Technical outliers
bgene42_idx = ALL_GENES.index('BGENE_0042')
for s in ['Sample_02', 'Sample_06']:
    j = SAMPLE_NAMES.index(s)
    counts[bgene42_idx, j] = int(counts[bgene42_idx, j] * 50)

bgene200_idx = ALL_GENES.index('BGENE_0200')
for s in ['Sample_15', 'Sample_23']:
    j = SAMPLE_NAMES.index(s)
    counts[bgene200_idx, j] = int(counts[bgene200_idx, j] * 30)

# ============================================================
# 6. Write to SQLite database
# ============================================================
output_dir = '/app/data'
os.makedirs(output_dir, exist_ok=True)
db_path = os.path.join(output_dir, 'experiment.db')

conn = sqlite3.connect(db_path)
c = conn.cursor()

# -- samples table --
c.execute('''CREATE TABLE samples (
    sample_id TEXT PRIMARY KEY,
    assigned_condition TEXT NOT NULL,
    processing_batch TEXT NOT NULL,
    extraction_date TEXT,
    operator_id TEXT
)''')

for s in SAMPLE_NAMES:
    idx = int(s.split('_')[1])
    batch = 'Batch1' if idx <= 12 else 'Batch2'
    date = '2024-03-15' if batch == 'Batch1' else '2024-03-22'
    operator = 'Tech_A' if batch == 'Batch1' else 'Tech_B'
    c.execute('INSERT INTO samples VALUES (?, ?, ?, ?, ?)',
              (s, METADATA_LABELS[s], batch, date, operator))

# -- genes table --
c.execute('''CREATE TABLE genes (
    symbol TEXT PRIMARY KEY,
    biotype TEXT DEFAULT "protein_coding",
    chromosome TEXT
)''')

# Use random calls AFTER count generation so they don't affect count values
for gene in ALL_GENES:
    chrom = f'chr{np.random.randint(1, 23)}'
    c.execute('INSERT INTO genes VALUES (?, ?, ?)',
              (gene, 'protein_coding', chrom))

# -- expression_data table (long / normalized format) --
c.execute('''CREATE TABLE expression_data (
    gene_symbol TEXT NOT NULL,
    sample_id TEXT NOT NULL,
    raw_count INTEGER NOT NULL,
    PRIMARY KEY (gene_symbol, sample_id),
    FOREIGN KEY (gene_symbol) REFERENCES genes(symbol),
    FOREIGN KEY (sample_id) REFERENCES samples(sample_id)
)''')

for i in range(N_GENES):
    for j in range(N_SAMPLES):
        c.execute('INSERT INTO expression_data VALUES (?, ?, ?)',
                  (ALL_GENES[i], SAMPLE_NAMES[j], int(counts[i, j])))

# -- sequencing_qc table --
c.execute('''CREATE TABLE sequencing_qc (
    sample_id TEXT PRIMARY KEY,
    total_fragments INTEGER,
    uniquely_mapped INTEGER,
    duplication_pct REAL,
    median_insert_size INTEGER,
    rin_score REAL,
    FOREIGN KEY (sample_id) REFERENCES samples(sample_id)
)''')

for j in range(N_SAMPLES):
    total = np.random.randint(15_000_000, 40_000_000)
    mapped = int(total * np.random.uniform(0.85, 0.95))
    dup = round(np.random.uniform(0.10, 0.30), 4)
    insert = np.random.randint(180, 300)
    rin = round(np.random.uniform(7.0, 10.0), 2)
    c.execute('INSERT INTO sequencing_qc VALUES (?, ?, ?, ?, ?, ?)',
              (SAMPLE_NAMES[j], total, mapped, dup, insert, rin))

# -- experiment_notes table --
c.execute('''CREATE TABLE experiment_notes (
    note_id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_date TEXT,
    author TEXT,
    note TEXT
)''')

notes = [
    ('2024-03-14', 'Dr. Chen', 'Experiment design finalized. Two conditions: Control and Treatment. 12 samples per condition.'),
    ('2024-03-15', 'Tech_A', 'Batch1 samples processed and submitted for sequencing.'),
    ('2024-03-18', 'Dr. Chen', 'Received report of possible sample mix-up during plating. Some wells may have been interchanged between condition plates.'),
    ('2024-03-22', 'Tech_B', 'Batch2 samples processed and submitted for sequencing. One week delay from Batch1 due to sequencer scheduling.'),
    ('2024-03-25', 'Tech_B', 'Initial QC passed for all samples. Library sizes and mapping rates within normal range.'),
    ('2024-03-28', 'Dr. Chen', 'Label on treatment reagent vial was damaged and unreadable. Cannot confirm perturbation identity from laboratory records alone.'),
]

for date, author, note in notes:
    c.execute('INSERT INTO experiment_notes (entry_date, author, note) VALUES (?, ?, ?)',
              (date, author, note))

conn.commit()
conn.close()

# ============================================================
# 7. Write pathway GMT file
# ============================================================
with open(os.path.join(output_dir, 'pathway_annotations.gmt'), 'w') as f:
    for pname, pgenes in PATHWAYS.items():
        f.write(pname + '\tna\t' + '\t'.join(pgenes) + '\n')

# ============================================================
# 8. Write README
# ============================================================
with open(os.path.join(output_dir, 'README.txt'), 'w') as f:
    f.write('RNA-seq Gene Expression Study\n')
    f.write('=' * 30 + '\n\n')
    f.write('24 cell culture samples profiled by RNA-seq.\n')
    f.write('Two experimental conditions: Control and Treatment.\n')
    f.write('Potential sample handling errors have been reported.\n')
    f.write('The identity of the perturbation applied to the treatment\n')
    f.write('group was lost due to a labeling accident.\n\n')
    f.write('Data files:\n')
    f.write('  experiment.db           - SQLite database with all experimental data\n')
    f.write('  pathway_annotations.gmt - Pathway gene sets (standard GMT format)\n\n')
    f.write('Database tables:\n')
    f.write('  Use "sqlite3 experiment.db" and ".tables" to explore.\n')

print(f'Generated {N_GENES} genes x {N_SAMPLES} samples')
print(f'Pathway neutral genes: {len(pathway_neutral)}')
print(f'Background genes: {len(BACKGROUND)}')
print(f'Database written to {db_path}')
