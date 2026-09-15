#!/usr/bin/env python3
"""Generate input data for the metagenome profiling audit task.

"""
import os

# ---- Taxonomy definition ----
# (tax_id, parent_id, rank)
NODES = [
    (1, 1, "no rank"),
    (131567, 1, "no rank"),
    (2, 131567, "superkingdom"),
    (2157, 131567, "superkingdom"),
    # Firmicutes lineage
    (1239, 2, "phylum"),
    (91061, 1239, "class"),
    (1385, 91061, "order"),
    (186826, 91061, "order"),
    (186817, 1385, "family"),
    (33958, 186826, "family"),
    (1386, 186817, "genus"),
    (1578, 33958, "genus"),
    (1396, 1386, "species"),
    (1590, 1578, "species"),
    # Proteobacteria lineage
    (1224, 2, "phylum"),
    (1236, 1224, "class"),
    (91347, 1236, "order"),
    (543, 91347, "family"),
    (561, 543, "genus"),
    (562, 561, "species"),
    # Bacteroidetes lineage
    (976, 2, "phylum"),
    (200643, 976, "class"),
    (171549, 200643, "order"),
    (815, 171549, "family"),
    (816, 815, "genus"),
    (817, 816, "species"),
    (818, 816, "species"),
    # Actinobacteria lineage
    (201174, 2, "phylum"),
    (1760, 201174, "class"),
    (85004, 1760, "order"),
    (31953, 85004, "family"),
    (1678, 31953, "genus"),
    (1680, 1678, "species"),
    # Archaea lineage
    (28890, 2157, "phylum"),
    (183925, 28890, "class"),
    (2158, 183925, "order"),
    (2159, 2158, "family"),
    (2160, 2159, "genus"),
    (145262, 2160, "species"),
]

# (tax_id, scientific_name)
NAMES = [
    (1, "root"),
    (131567, "cellular organisms"),
    (2, "Bacteria"),
    (2157, "Archaea"),
    (1239, "Firmicutes"),
    (91061, "Bacilli"),
    (1385, "Bacillales"),
    (186826, "Lactobacillales"),
    (186817, "Bacillaceae"),
    (33958, "Lactobacillaceae"),
    (1386, "Bacillus"),
    (1578, "Lactobacillus"),
    (1396, "Bacillus cereus"),
    (1590, "Lactobacillus plantarum"),
    (1224, "Proteobacteria"),
    (1236, "Gammaproteobacteria"),
    (91347, "Enterobacterales"),
    (543, "Enterobacteriaceae"),
    (561, "Escherichia"),
    (562, "Escherichia coli"),
    (976, "Bacteroidetes"),
    (200643, "Bacteroidia"),
    (171549, "Bacteroidales"),
    (815, "Bacteroidaceae"),
    (816, "Bacteroides"),
    (817, "Bacteroides fragilis"),
    (818, "Bacteroides thetaiotaomicron"),
    (201174, "Actinobacteria"),
    (1760, "Actinomycetia"),
    (85004, "Bifidobacteriales"),
    (31953, "Bifidobacteriaceae"),
    (1678, "Bifidobacterium"),
    (1680, "Bifidobacterium adolescentis"),
    (28890, "Euryarchaeota"),
    (183925, "Methanobacteria"),
    (2158, "Methanobacteriales"),
    (2159, "Methanobacteriaceae"),
    (2160, "Methanobacterium"),
    (145262, "Methanobacterium paludis"),
]

# Merged taxids: (old_tax_id, new_tax_id)
MERGED = [
    (74313, 562),
    (29461, 817),
    (119065, 816),
]

# Tax paths: taxid -> (taxpath_ids, taxpath_names)
TAXPATHS = {
    2: ("2", "Bacteria"),
    2157: ("2157", "Archaea"),
    1239: ("2|1239", "Bacteria|Firmicutes"),
    1224: ("2|1224", "Bacteria|Proteobacteria"),
    976: ("2|976", "Bacteria|Bacteroidetes"),
    201174: ("2|201174", "Bacteria|Actinobacteria"),
    28890: ("2157|28890", "Archaea|Euryarchaeota"),
    91061: ("2|1239|91061", "Bacteria|Firmicutes|Bacilli"),
    1236: ("2|1224|1236", "Bacteria|Proteobacteria|Gammaproteobacteria"),
    200643: ("2|976|200643", "Bacteria|Bacteroidetes|Bacteroidia"),
    1760: ("2|201174|1760", "Bacteria|Actinobacteria|Actinomycetia"),
    183925: ("2157|28890|183925", "Archaea|Euryarchaeota|Methanobacteria"),
    1385: ("2|1239|91061|1385", "Bacteria|Firmicutes|Bacilli|Bacillales"),
    186826: ("2|1239|91061|186826", "Bacteria|Firmicutes|Bacilli|Lactobacillales"),
    91347: ("2|1224|1236|91347", "Bacteria|Proteobacteria|Gammaproteobacteria|Enterobacterales"),
    171549: ("2|976|200643|171549", "Bacteria|Bacteroidetes|Bacteroidia|Bacteroidales"),
    85004: ("2|201174|1760|85004", "Bacteria|Actinobacteria|Actinomycetia|Bifidobacteriales"),
    2158: ("2157|28890|183925|2158", "Archaea|Euryarchaeota|Methanobacteria|Methanobacteriales"),
    186817: ("2|1239|91061|1385|186817", "Bacteria|Firmicutes|Bacilli|Bacillales|Bacillaceae"),
    33958: ("2|1239|91061|186826|33958", "Bacteria|Firmicutes|Bacilli|Lactobacillales|Lactobacillaceae"),
    543: ("2|1224|1236|91347|543", "Bacteria|Proteobacteria|Gammaproteobacteria|Enterobacterales|Enterobacteriaceae"),
    815: ("2|976|200643|171549|815", "Bacteria|Bacteroidetes|Bacteroidia|Bacteroidales|Bacteroidaceae"),
    31953: ("2|201174|1760|85004|31953", "Bacteria|Actinobacteria|Actinomycetia|Bifidobacteriales|Bifidobacteriaceae"),
    2159: ("2157|28890|183925|2158|2159", "Archaea|Euryarchaeota|Methanobacteria|Methanobacteriales|Methanobacteriaceae"),
    1386: ("2|1239|91061|1385|186817|1386", "Bacteria|Firmicutes|Bacilli|Bacillales|Bacillaceae|Bacillus"),
    1578: ("2|1239|91061|186826|33958|1578", "Bacteria|Firmicutes|Bacilli|Lactobacillales|Lactobacillaceae|Lactobacillus"),
    561: ("2|1224|1236|91347|543|561", "Bacteria|Proteobacteria|Gammaproteobacteria|Enterobacterales|Enterobacteriaceae|Escherichia"),
    816: ("2|976|200643|171549|815|816", "Bacteria|Bacteroidetes|Bacteroidia|Bacteroidales|Bacteroidaceae|Bacteroides"),
    1678: ("2|201174|1760|85004|31953|1678", "Bacteria|Actinobacteria|Actinomycetia|Bifidobacteriales|Bifidobacteriaceae|Bifidobacterium"),
    2160: ("2157|28890|183925|2158|2159|2160", "Archaea|Euryarchaeota|Methanobacteria|Methanobacteriales|Methanobacteriaceae|Methanobacterium"),
    1396: ("2|1239|91061|1385|186817|1386|1396", "Bacteria|Firmicutes|Bacilli|Bacillales|Bacillaceae|Bacillus|Bacillus cereus"),
    1590: ("2|1239|91061|186826|33958|1578|1590", "Bacteria|Firmicutes|Bacilli|Lactobacillales|Lactobacillaceae|Lactobacillus|Lactobacillus plantarum"),
    562: ("2|1224|1236|91347|543|561|562", "Bacteria|Proteobacteria|Gammaproteobacteria|Enterobacterales|Enterobacteriaceae|Escherichia|Escherichia coli"),
    817: ("2|976|200643|171549|815|816|817", "Bacteria|Bacteroidetes|Bacteroidia|Bacteroidales|Bacteroidaceae|Bacteroides|Bacteroides fragilis"),
    818: ("2|976|200643|171549|815|816|818", "Bacteria|Bacteroidetes|Bacteroidia|Bacteroidales|Bacteroidaceae|Bacteroides|Bacteroides thetaiotaomicron"),
    1680: ("2|201174|1760|85004|31953|1678|1680", "Bacteria|Actinobacteria|Actinomycetia|Bifidobacteriales|Bifidobacteriaceae|Bifidobacterium|Bifidobacterium adolescentis"),
    145262: ("2157|28890|183925|2158|2159|2160|145262", "Archaea|Euryarchaeota|Methanobacteria|Methanobacteriales|Methanobacteriaceae|Methanobacterium|Methanobacterium paludis"),
}

# Merged taxid TAXPATH overrides (old taxonomy paths)
MERGED_TAXPATHS = {
    74313: ("2|1224|1236|91347|543|561|74313",
            "Bacteria|Proteobacteria|Gammaproteobacteria|Enterobacterales|Enterobacteriaceae|Escherichia|Escherichia coli K-12"),
    29461: ("2|976|200643|171549|815|816|29461",
            "Bacteria|Bacteroidetes|Bacteroidia|Bacteroidales|Bacteroidaceae|Bacteroides|Bacteroides fragilis NCTC 9343"),
}


# ---- I/O helpers ----

def write_nodes_dmp(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        for tax_id, parent_id, rank in NODES:
            fields = [
                str(tax_id), str(parent_id), rank,
                "", "0", "0", "1", "0", "0", "0", "0", "0", ""
            ]
            f.write("\t|\t".join(fields) + "\t|\n")


def write_names_dmp(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        for tax_id, name in NAMES:
            f.write(f"{tax_id}\t|\t{name}\t|\t\t|\tscientific name\t|\n")


def write_merged_dmp(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        for old_id, new_id in MERGED:
            f.write(f"{old_id}\t|\t{new_id}\t|\n")


def build_entries(cereus, plantarum, coli, fragilis, theta, adolescentis, paludis):
    """Build full 7-rank profile entries from species abundances.

    Returns list of (taxid, rank, percentage) tuples.
    Higher ranks are derived by summing species in the lineage.
    """
    firmicutes = cereus + plantarum
    proteo = coli
    bacteroidetes = fragilis + theta
    actino = adolescentis
    euryarchaeota = paludis
    bacteria = firmicutes + proteo + bacteroidetes + actino
    archaea = euryarchaeota

    return [
        (2, "superkingdom", bacteria),
        (2157, "superkingdom", archaea),
        (1239, "phylum", firmicutes),
        (1224, "phylum", proteo),
        (976, "phylum", bacteroidetes),
        (201174, "phylum", actino),
        (28890, "phylum", euryarchaeota),
        (91061, "class", firmicutes),
        (1236, "class", proteo),
        (200643, "class", bacteroidetes),
        (1760, "class", actino),
        (183925, "class", euryarchaeota),
        (1385, "order", cereus),
        (186826, "order", plantarum),
        (91347, "order", proteo),
        (171549, "order", bacteroidetes),
        (85004, "order", actino),
        (2158, "order", euryarchaeota),
        (186817, "family", cereus),
        (33958, "family", plantarum),
        (543, "family", proteo),
        (815, "family", bacteroidetes),
        (31953, "family", actino),
        (2159, "family", euryarchaeota),
        (1386, "genus", cereus),
        (1578, "genus", plantarum),
        (561, "genus", proteo),
        (816, "genus", bacteroidetes),
        (1678, "genus", actino),
        (2160, "genus", euryarchaeota),
        (1396, "species", cereus),
        (1590, "species", plantarum),
        (562, "species", proteo),
        (817, "species", fragilis),
        (818, "species", theta),
        (1680, "species", actino),
        (145262, "species", euryarchaeota),
    ]


def _write_entry(f, entry):
    """Write one profile entry line."""
    if len(entry) == 5:
        taxid, rank, pct, tp_override, tpsn_override = entry
        taxpath = tp_override
        taxpathsn = tpsn_override
    else:
        taxid, rank, pct = entry
        taxpath, taxpathsn = TAXPATHS[taxid]
    f.write(f"{taxid}\t{rank}\t{taxpath}\t{taxpathsn}\t{pct:.5f}\n")


def write_profile(path, sample_entries):
    """Write a standard CAMI profiling format file.

    sample_entries: list of (sample_id, entries_list)
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write("#CAMI Submission for Taxonomic Profiling\n")
        f.write("@Version:0.9.1\n")
        f.write("@Ranks:superkingdom|phylum|class|order|family|genus|species|strain\n")
        for sample_id, entries in sample_entries:
            f.write(f"\n@SampleID:{sample_id}\n")
            f.write("@@TAXID\tRANK\tTAXPATH\tTAXPATHSN\tPERCENTAGE\n")
            for entry in entries:
                _write_entry(f, entry)


def write_echo_profile(path, s1_entries, s2_entries):
    """Write echo's profile with MISSING @SampleID for S2."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write("#CAMI Submission for Taxonomic Profiling\n")
        f.write("@Version:0.9.1\n")
        f.write("@Ranks:superkingdom|phylum|class|order|family|genus|species|strain\n")
        # S1 - proper header
        f.write("\n@SampleID:S1\n")
        f.write("@@TAXID\tRANK\tTAXPATH\tTAXPATHSN\tPERCENTAGE\n")
        for entry in s1_entries:
            _write_entry(f, entry)
        # S2 - MISSING @SampleID line (the defect)
        f.write("@@TAXID\tRANK\tTAXPATH\tTAXPATHSN\tPERCENTAGE\n")
        for entry in s2_entries:
            _write_entry(f, entry)


# ---- Species-level data for each tool/sample ----
# Format: (cereus, plantarum, coli, fragilis, theta, adolescentis, paludis)

# Gold standard
GS_S1 = (20.0, 30.0, 12.0, 15.0, 10.0, 10.5, 2.5)
GS_S2 = (15.0, 25.0, 18.0, 20.0, 10.0, 10.0, 2.0)

# profiler_alpha: clean, moderate accuracy
ALPHA_S1 = (19.0, 29.0, 11.5, 17.0, 8.0, 10.5, 2.0)
ALPHA_S2 = (14.0, 24.0, 19.0, 22.0, 8.0, 10.0, 2.5)

# profiler_bravo: uses merged/deprecated taxids for E. coli and B. fragilis
# 74313 replaces 562 (E. coli K-12 merged into E. coli)
# 29461 replaces 817 (B. fragilis NCTC 9343 merged into B. fragilis)
BRAVO_S1 = (21.0, 28.0, 13.0, 14.0, 11.0, 10.5, 2.5)
BRAVO_S2 = (16.0, 24.0, 19.0, 19.0, 10.0, 10.0, 2.0)

# profiler_charlie: abundance overflow in S1 (species sum = 110)
CHARLIE_S1 = (22.0, 33.0, 13.2, 16.5, 11.0, 11.0, 3.3)  # sum=110.0
CHARLIE_S2 = (14.0, 26.0, 17.0, 21.0, 9.0, 11.0, 2.0)

# profiler_delta: duplicate taxid 817 in S2 at species level
DELTA_S1 = (19.0, 31.0, 12.0, 16.0, 9.0, 10.5, 2.5)
DELTA_S2_INTENDED = (16.0, 24.0, 17.0, 22.0, 9.0, 10.0, 2.0)
# fragilis=22 will be split as two entries: 15.0 and 7.0

# profiler_echo: missing @SampleID header for S2
ECHO_S1 = (18.0, 31.0, 12.5, 16.0, 9.0, 11.0, 2.5)
ECHO_S2 = (14.0, 24.0, 19.0, 21.0, 9.0, 11.0, 2.0)


def build_bravo_entries(cereus, plantarum, coli, fragilis, theta, adolescentis, paludis):
    """Build bravo's entries: higher ranks use current taxids, species uses merged taxids."""
    entries = build_entries(cereus, plantarum, coli, fragilis, theta, adolescentis, paludis)
    # Remove the current-taxid species entries for E. coli and B. fragilis
    entries = [e for e in entries if not (e[0] == 562 and e[1] == "species")
                                  and not (e[0] == 817 and e[1] == "species")]
    # Add entries with old/merged taxids and overridden TAXPATH
    tp_74313, tpsn_74313 = MERGED_TAXPATHS[74313]
    tp_29461, tpsn_29461 = MERGED_TAXPATHS[29461]
    entries.append((74313, "species", coli, tp_74313, tpsn_74313))
    entries.append((29461, "species", fragilis, tp_29461, tpsn_29461))
    return entries


def build_delta_s2_entries():
    """Build delta S2 entries with duplicate taxid 817 at species level."""
    cereus, plantarum, coli, fragilis, theta, adolescentis, paludis = DELTA_S2_INTENDED
    # Build normal entries using the intended (summed) fragilis value for higher ranks
    entries = build_entries(cereus, plantarum, coli, fragilis, theta, adolescentis, paludis)
    # Remove the single 817 species entry
    entries = [e for e in entries if not (e[0] == 817 and e[1] == "species")]
    # Add two duplicate entries for 817 that sum to fragilis (22 = 15 + 7)
    entries.append((817, "species", 15.0))
    entries.append((817, "species", 7.0))
    return entries


def main():
    base = "/opt/taskdata"

    # Write taxonomy files
    write_nodes_dmp(os.path.join(base, "taxonomy", "nodes.dmp"))
    write_names_dmp(os.path.join(base, "taxonomy", "names.dmp"))
    write_merged_dmp(os.path.join(base, "taxonomy", "merged.dmp"))

    # Write gold standard
    write_profile(
        os.path.join(base, "gold_standard.profile"),
        [("S1", build_entries(*GS_S1)), ("S2", build_entries(*GS_S2))],
    )

    sub_dir = os.path.join(base, "submissions")
    os.makedirs(sub_dir, exist_ok=True)

    # profiler_alpha: clean
    write_profile(
        os.path.join(sub_dir, "profiler_alpha.profile"),
        [("S1", build_entries(*ALPHA_S1)), ("S2", build_entries(*ALPHA_S2))],
    )

    # profiler_bravo: merged taxids at species level
    write_profile(
        os.path.join(sub_dir, "profiler_bravo.profile"),
        [("S1", build_bravo_entries(*BRAVO_S1)),
         ("S2", build_bravo_entries(*BRAVO_S2))],
    )

    # profiler_charlie: abundance overflow in S1
    write_profile(
        os.path.join(sub_dir, "profiler_charlie.profile"),
        [("S1", build_entries(*CHARLIE_S1)), ("S2", build_entries(*CHARLIE_S2))],
    )

    # profiler_delta: duplicate taxid in S2
    write_profile(
        os.path.join(sub_dir, "profiler_delta.profile"),
        [("S1", build_entries(*DELTA_S1)), ("S2", build_delta_s2_entries())],
    )

    # profiler_echo: missing @SampleID for S2
    write_echo_profile(
        os.path.join(sub_dir, "profiler_echo.profile"),
        build_entries(*ECHO_S1),
        build_entries(*ECHO_S2),
    )

    print("Data generation complete.")


if __name__ == "__main__":
    main()
