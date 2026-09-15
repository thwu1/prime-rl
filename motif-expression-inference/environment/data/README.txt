Regulatory Genomics Multi-omic Dataset
======================================

This dataset contains multi-omic data from a synthetic regulatory
system involving 8 transcription factors (TF_A through TF_H).

Files
-----
motifs.meme
  Position Weight Matrices for 8 TFs in standard MEME format.

promoters_train.fa
  150 promoter DNA sequences (800 bp each), FASTA format.
  Gene IDs: GENE_001 to GENE_150.

promoters_test.fa
  50 promoter DNA sequences (800 bp each), FASTA format.
  Gene IDs: GENE_151 to GENE_200.

accessibility.bed
  ATAC-seq chromatin accessibility peaks across all 200 promoters.
  BED6 format: chrom, start, end, name, score, strand.

expression_train.tsv
  Gene expression for 150 training genes.
  Tab-separated: gene_id, expression.

chipseq_TFC.narrowPeak
  ChIP-seq peaks for TF_C across all promoters.
  Standard ENCODE narrowPeak format (10 columns).

genome.sizes
  Promoter sizes for genomic tools. Tab-separated: chrom, size.
