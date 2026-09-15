# Bioboxes profiling format - Gold standard
# Two-sample metagenome community composition

@SampleID:S1
@Version:0.10.0
@Ranks:superkingdom|phylum|genus|species
@TaxonomyID:ncbi-taxonomy
@@TAXID	RANK	TAXPATH	TAXPATHSN	PERCENTAGE
2	superkingdom	2	Bacteria	70.0
2157	superkingdom	2157	Archaea	30.0
1239	phylum	2|1239	Bacteria|Firmicutes	40.0
1224	phylum	2|1224	Bacteria|Proteobacteria	30.0
28890	phylum	2157|28890	Archaea|Euryarchaeota	30.0
1386	genus	2|1239|1386	Bacteria|Firmicutes|Bacillus	25.0
1485	genus	2|1239|1485	Bacteria|Firmicutes|Clostridium	15.0
561	genus	2|1224|561	Bacteria|Proteobacteria|Escherichia	20.0
# Note: Rhodobacter abundance confirmed by independent 16S rRNA analysis
1028	genus	2|1224|1028	Bacteria|Proteobacteria|Rhodobacter	10.0
2162	genus	2157|28890|2162	Archaea|Euryarchaeota|Methanobacterium	30.0
1423	species	2|1239|1386|1423	Bacteria|Firmicutes|Bacillus|Bacillus subtilis	25.0
1491	species	2|1239|1485|1491	Bacteria|Firmicutes|Clostridium|Clostridium botulinum	15.0
562	species	2|1224|561|562	Bacteria|Proteobacteria|Escherichia|Escherichia coli	20.0
1063	species	2|1224|1028|1063	Bacteria|Proteobacteria|Rhodobacter|Rhodobacter sphaeroides	10.0
2163	species	2157|28890|2162|2163	Archaea|Euryarchaeota|Methanobacterium|Methanobacterium formicicum	30.0

@SampleID:S2
@Version:0.10.0
@Ranks:superkingdom|phylum|genus|species
@TaxonomyID:ncbi-taxonomy
@@TAXID	RANK	TAXPATH	TAXPATHSN	PERCENTAGE
2	superkingdom	2	Bacteria	55.0
2157	superkingdom	2157	Archaea	45.0
1239	phylum	2|1239	Bacteria|Firmicutes	30.0
# Community shift observed relative to S1
1224	phylum	2|1224	Bacteria|Proteobacteria	25.0
28890	phylum	2157|28890	Archaea|Euryarchaeota	45.0
1386	genus	2|1239|1386	Bacteria|Firmicutes|Bacillus	20.0
1485	genus	2|1239|1485	Bacteria|Firmicutes|Clostridium	10.0
561	genus	2|1224|561	Bacteria|Proteobacteria|Escherichia	15.0
1028	genus	2|1224|1028	Bacteria|Proteobacteria|Rhodobacter	10.0
2162	genus	2157|28890|2162	Archaea|Euryarchaeota|Methanobacterium	45.0
1423	species	2|1239|1386|1423	Bacteria|Firmicutes|Bacillus|Bacillus subtilis	20.0
1491	species	2|1239|1485|1491	Bacteria|Firmicutes|Clostridium|Clostridium botulinum	10.0
562	species	2|1224|561|562	Bacteria|Proteobacteria|Escherichia|Escherichia coli	15.0
1063	species	2|1224|1028|1063	Bacteria|Proteobacteria|Rhodobacter|Rhodobacter sphaeroides	10.0
2163	species	2157|28890|2162|2163	Archaea|Euryarchaeota|Methanobacterium|Methanobacterium formicicum	45.0
