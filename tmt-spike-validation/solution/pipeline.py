#!/usr/bin/env python3
"""TMT spike-in proteomics quantification assessment pipeline for PXD000001."""


import json
import math
import os
import re
import ssl
import statistics
import sys
import time
import urllib.request
from collections import defaultdict

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AA_MASS = {
    'G': 57.02146, 'A': 71.03711, 'V': 99.06841, 'L': 113.08406,
    'I': 113.08406, 'P': 97.05276, 'F': 147.06841, 'W': 186.07931,
    'M': 131.04049, 'S': 87.03203, 'T': 101.04768, 'C': 103.00919,
    'Y': 163.06333, 'H': 137.05891, 'D': 115.02694, 'E': 129.04259,
    'N': 114.04293, 'Q': 128.05858, 'K': 128.09496, 'R': 156.10111,
}
WATER_MASS = 18.01056

SPIKE_PATTERNS = {
    'ENO1_YEAST': 'enolase_spike',
    'ALBU_BOVIN': 'bsa_spike',
    'PYGM_RABIT': 'phosb_spike',
    'CYC_BOVIN': 'cytc_spike',
}

CATEGORY_KEYWORDS = {
    'erwinia': 'erwinia',
    'enolase': 'enolase_spike',
    'bsa': 'bsa_spike',
    'phosb': 'phosb_spike',
    'phosphorylase': 'phosb_spike',
    'cytochrome': 'cytc_spike',
}

PROJECT_ID = 'PXD000001'

# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------


def http_get(url, accept='application/json', timeout=120):
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={'Accept': accept})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.read()
    except Exception as e:
        print(f'  HTTP GET failed ({url}): {e}')
        return None


def api_get_json(url, retries=3):
    for attempt in range(retries):
        raw = http_get(url)
        if raw is not None:
            text = raw.decode('utf-8').strip()
            if text:
                try:
                    return json.loads(text)
                except json.JSONDecodeError as e:
                    print(f'  JSON parse error on attempt {attempt + 1}: {e}')
        if attempt < retries - 1:
            time.sleep(2 ** attempt)
    return None


def download_file(url, dest, retries=3):
    urls_to_try = []
    if url.startswith('ftp://'):
        urls_to_try.append(url.replace('ftp://', 'https://', 1))
    urls_to_try.append(url)
    ctx = ssl.create_default_context()
    for download_url in urls_to_try:
        for attempt in range(retries):
            try:
                req = urllib.request.Request(download_url)
                with urllib.request.urlopen(req, timeout=300, context=ctx) as resp:
                    with open(dest, 'wb') as fout:
                        while True:
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            fout.write(chunk)
                if os.path.getsize(dest) > 0:
                    return True
            except Exception as e:
                print(f'  Download attempt {attempt+1} failed ({download_url}): {e}')
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
    return False


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def parse_fasta(path):
    proteins = {}
    cur_id = None
    cur_seq = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith('>'):
                if cur_id is not None:
                    proteins[cur_id] = ''.join(cur_seq)
                cur_id = line[1:].split()[0]
                cur_seq = []
            elif cur_id is not None:
                cur_seq.append(line)
    if cur_id is not None:
        proteins[cur_id] = ''.join(cur_seq)
    return proteins


def tryptic_digest(sequence, max_missed=2, min_length=6):
    sites = [0]
    for i in range(len(sequence)):
        if sequence[i] in ('K', 'R'):
            if i + 1 < len(sequence) and sequence[i + 1] == 'P':
                continue
            sites.append(i + 1)
    sites.append(len(sequence))
    peptides = set()
    for mc in range(max_missed + 1):
        for i in range(len(sites) - 1 - mc):
            pep = sequence[sites[i]:sites[i + 1 + mc]]
            if len(pep) >= min_length:
                peptides.add(pep)
    return peptides


def parse_mztab(path):
    peptides = []
    tmt_start = None
    with open(path) as f:
        for line in f:
            line = line.rstrip('\n\r')
            if not line:
                continue
            parts = line.split('\t')
            row_type = parts[0]
            if row_type == 'PEH':
                for idx, col in enumerate(parts):
                    if 'peptide_abundance_sub[1]' in col:
                        tmt_start = idx
                        break
            elif row_type == 'PEP' and tmt_start is not None:
                seq = parts[1]
                acc = parts[2]
                tmt_vals = []
                for j in range(6):
                    ci = tmt_start + j
                    if ci < len(parts):
                        raw = parts[ci].strip()
                        if raw in ('--', 'null', '', 'NA', 'NaN'):
                            tmt_vals.append(None)
                        else:
                            try:
                                tmt_vals.append(float(raw))
                            except ValueError:
                                tmt_vals.append(None)
                    else:
                        tmt_vals.append(None)
                peptides.append({
                    'sequence': seq,
                    'accession': acc,
                    'tmt': tmt_vals,
                })
    return peptides


def monoisotopic_mass(sequence):
    mass = WATER_MASS
    for aa in sequence:
        if aa not in AA_MASS:
            return None
        mass += AA_MASS[aa]
    return round(mass, 4)


def classify_protein(accession):
    for pattern, category in SPIKE_PATTERNS.items():
        if pattern in accession:
            return category
    if accession.startswith('ECA'):
        return 'erwinia'
    return 'unclassified'


# ---------------------------------------------------------------------------
# Expected ratio extraction from project description
# ---------------------------------------------------------------------------


def parse_expected_ratios(description):
    """Parse expected TMT ratios from the project description text."""
    ratio_re = re.compile(
        r'([\d.]+):([\d.]+):([\d.]+):([\d.]+):([\d.]+):([\d.]+)'
    )
    categories = {}
    parts = ratio_re.split(description)

    for i in range(0, len(parts) - 6, 7):
        text_before = parts[i].lower()
        ratios = [float(parts[i + j]) for j in range(1, 7)]

        ch1 = ratios[0]
        if ch1 > 0:
            norm = [round(r / ch1, 4) for r in ratios]
        else:
            norm = [round(r, 4) for r in ratios]

        cat = None
        for keyword, category in CATEGORY_KEYWORDS.items():
            if keyword in text_before:
                cat = category
                break

        if cat is not None:
            categories[cat] = norm

    return categories


# ---------------------------------------------------------------------------
# PRIDE API interaction
# ---------------------------------------------------------------------------


def fetch_project_info():
    api_urls = [
        f'https://www.ebi.ac.uk/pride/ws/archive/v3/projects/{PROJECT_ID}',
        f'https://www.ebi.ac.uk/pride/ws/archive/v2/projects/{PROJECT_ID}',
    ]
    for url in api_urls:
        data = api_get_json(url)
        if data and isinstance(data, dict) and 'title' in data:
            return data.get('title', 'TMT spikes'), data.get('projectDescription', '')
    return 'TMT spikes', ''


def discover_file_urls():
    mztab_url = None
    fasta_url = None

    files_endpoints = [
        f'https://www.ebi.ac.uk/pride/ws/archive/v3/projects/{PROJECT_ID}/files/all',
        f'https://www.ebi.ac.uk/pride/ws/archive/v3/projects/{PROJECT_ID}/files?pageSize=200',
    ]

    for endpoint in files_endpoints:
        files = api_get_json(endpoint)
        if not files or not isinstance(files, list):
            continue
        for fobj in files:
            fname = fobj.get('fileName', '')
            for loc in fobj.get('publicFileLocations', []):
                val = loc.get('value', '')
                if 'ftp.pride.ebi.ac.uk' in val:
                    if fname.endswith('-mztab.txt') and 'dat-mztab' in fname:
                        mztab_url = val
                    elif fname.endswith('.fasta'):
                        fasta_url = val
        if mztab_url and fasta_url:
            break

    if not mztab_url:
        mztab_url = 'https://ftp.pride.ebi.ac.uk/pride/data/archive/2012/03/PXD000001/F063721.dat-mztab.txt'
        print('  Using fallback mzTab URL')
    if not fasta_url:
        fasta_url = 'https://ftp.pride.ebi.ac.uk/pride/data/archive/2012/03/PXD000001/erwinia_carotovora.fasta'
        print('  Using fallback FASTA URL')

    return mztab_url, fasta_url


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------


def compute_rmsd(observed, expected):
    sq_diff = [(o - e) ** 2 for o, e in zip(observed, expected)]
    return round(math.sqrt(sum(sq_diff) / len(sq_diff)), 4)


def compute_per_protein_cv(prot_pep_ratios):
    cvs = {}
    for acc, ratio_lists in prot_pep_ratios.items():
        if len(ratio_lists) < 3:
            continue
        channel_cvs = []
        for ch in range(6):
            ch_vals = [r[ch] for r in ratio_lists]
            mean_val = statistics.mean(ch_vals)
            if mean_val > 0 and len(ch_vals) >= 2:
                stdev = statistics.stdev(ch_vals)
                channel_cvs.append(stdev / mean_val)
            else:
                channel_cvs.append(0.0)
        cvs[acc] = round(statistics.mean(channel_cvs), 4)
    return cvs


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def main():
    os.makedirs('/app', exist_ok=True)

    # Fetch project metadata and description
    print('Fetching project metadata...')
    project_title, project_description = fetch_project_info()
    print(f'  Title: {project_title}')

    # Parse expected ratios from the project description
    print('Parsing expected ratios from description...')
    spike_expected_ratios = parse_expected_ratios(project_description)
    for cat, ratios in spike_expected_ratios.items():
        print(f'  {cat}: {ratios}')

    # Discover file download URLs
    print('Discovering file URLs...')
    mztab_url, fasta_url = discover_file_urls()

    # Download files
    print('Downloading data files...')
    mztab_path = '/app/mztab.txt'
    fasta_path = '/app/erwinia.fasta'

    if not download_file(mztab_url, mztab_path):
        download_file(
            'https://ftp.pride.ebi.ac.uk/pride/data/archive/2012/03/PXD000001/F063721.dat-mztab.txt',
            mztab_path,
        )
    if not download_file(fasta_url, fasta_path):
        download_file(
            'https://ftp.pride.ebi.ac.uk/pride/data/archive/2012/03/PXD000001/erwinia_carotovora.fasta',
            fasta_path,
        )

    for label, path in [('mzTab', mztab_path), ('FASTA', fasta_path)]:
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            print(f'ERROR: Failed to download {label}', file=sys.stderr)
            sys.exit(1)

    # Parse FASTA
    print('Parsing FASTA...')
    proteins = parse_fasta(fasta_path)
    print(f'  {len(proteins)} proteins')

    # Parse mzTab
    print('Parsing mzTab...')
    peptides = parse_mztab(mztab_path)
    print(f'  {len(peptides)} peptides')

    # Tryptic validation
    print('Validating peptides against tryptic digest...')
    tryptic_db = {pid: tryptic_digest(seq) for pid, seq in proteins.items()}
    valid_tryptic = 0
    invalid_tryptic = 0
    for pep in peptides:
        acc = pep['accession']
        if acc in tryptic_db:
            if pep['sequence'] in tryptic_db[acc]:
                valid_tryptic += 1
            else:
                invalid_tryptic += 1
    checked = valid_tryptic + invalid_tryptic
    tryptic_pct = round(valid_tryptic / max(1, checked) * 100, 2)
    print(f'  Valid: {valid_tryptic}, Invalid: {invalid_tryptic}, '
          f'Coverage: {tryptic_pct}%')

    # Compute masses
    print('Computing monoisotopic masses...')
    pep_masses = {}
    for pep in peptides:
        seq = pep['sequence']
        if seq not in pep_masses:
            m = monoisotopic_mass(seq)
            if m is not None:
                pep_masses[seq] = m
    print(f'  {len(pep_masses)} unique peptides')

    # TMT ratios
    print('Computing TMT ratios...')
    prot_pep_ratios = defaultdict(list)
    for pep in peptides:
        tmt = pep['tmt']
        if len(tmt) == 6 and all(v is not None and v > 0 for v in tmt):
            norm = [v / tmt[0] for v in tmt]
            prot_pep_ratios[pep['accession']].append(norm)

    prot_ratios = {}
    for acc, ratio_lists in prot_pep_ratios.items():
        med = []
        for ch in range(6):
            ch_vals = [r[ch] for r in ratio_lists]
            med.append(round(statistics.median(ch_vals), 4))
        prot_ratios[acc] = med
    print(f'  {len(prot_ratios)} proteins with ratios')

    # Classification
    print('Classifying proteins...')
    classes = defaultdict(list)
    for acc in prot_ratios:
        cls = classify_protein(acc)
        classes[cls].append(acc)
    for cat in ['erwinia', 'enolase_spike', 'bsa_spike',
                'phosb_spike', 'cytc_spike', 'unclassified']:
        if cat not in classes:
            classes[cat] = []

    # Per-protein CV
    print('Computing per-protein CV...')
    per_protein_cv = compute_per_protein_cv(prot_pep_ratios)
    print(f'  {len(per_protein_cv)} proteins with CV')

    # Ratio RMSD per category
    print('Computing ratio RMSD...')
    ratio_rmsd = {}
    for cat, expected in spike_expected_ratios.items():
        cat_proteins = classes.get(cat, [])
        cat_ratios = [prot_ratios[acc] for acc in cat_proteins
                      if acc in prot_ratios]
        if cat_ratios:
            mean_observed = []
            for ch in range(6):
                ch_vals = [r[ch] for r in cat_ratios]
                mean_observed.append(statistics.mean(ch_vals))
            ratio_rmsd[cat] = compute_rmsd(mean_observed, expected)
        else:
            ratio_rmsd[cat] = 0.0
    print(f'  RMSD: {ratio_rmsd}')

    # Write output
    print('Writing results...')
    results = {
        'project_accession': PROJECT_ID,
        'project_title': project_title,
        'total_peptides': len(peptides),
        'total_proteins': len(prot_ratios),
        'valid_tryptic_peptides': valid_tryptic,
        'invalid_tryptic_peptides': invalid_tryptic,
        'tryptic_coverage_pct': tryptic_pct,
        'protein_classifications': {k: sorted(v) for k, v in classes.items()},
        'protein_ratios': prot_ratios,
        'peptide_masses': pep_masses,
        'spike_expected_ratios': spike_expected_ratios,
        'ratio_rmsd': ratio_rmsd,
        'per_protein_cv': per_protein_cv,
    }

    output_path = '/app/results.json'
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    print(f'\nPipeline complete. Results at {output_path}')


if __name__ == '__main__':
    main()
