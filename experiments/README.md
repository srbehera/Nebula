# Introduction

This README files provides instructions on how to reproduce the results presented on the journal version of Nebula, submitted to Oxford Nucleic Acid Research in June 2020.

# Data

We used the SV calls made by <cite>[Chaisson et al][1]</cite> on 1KG samples [HG00514](http://ftp.1000genomes.ebi.ac.uk/vol1/ftp/data_collections/hgsv_sv_discovery/data/CHS/HG00514/), [HG00733](http://ftp.1000genomes.ebi.ac.uk/vol1/ftp/data_collections/hgsv_sv_discovery/data/PUR/HG00733/) and [NA19240](http://ftp.1000genomes.ebi.ac.uk/vol1/ftp/data_collections/hgsv_sv_discovery/data/YRI/NA19240/high_cov_alignment/) as the basis of this study. The deletion and insertion calls can be retrievd from [this link](http://ftp.1000genomes.ebi.ac.uk/vol1/ftp/data_collections/hgsv_sv_discovery/working/20180627_PanTechnologyIntegrationSet/). The inversion calls can be retrived from dbVar's ftp website [here](https://ftp.ncbi.nlm.nih.gov/pub/dbVar/data/Homo_sapiens/by_study/genotype/nstd152/).

## Deletions and Insertions

As Nebula genotypes SVs purely based on coordinates, we have done slight modifications to the calls above to make genotyping results more consistent.

For overlapping deletions, we only keep the one with the smallest `BEGIN` position and discard the rest.

For insertions, we are assuming that the `END` field in the `INFO` section is set to `BEGIN + 1`. We have modified calls that don't adhere to this assumption. Sometimes, the same insertion, or one with different inserted sequence, are reported on very close coordiates between the three samples. These will be considered different events by Nebula, but probably not by a mapping-based genotyper. To keep the final results consistent, we are merging such events into a single event across the three samples. This "unification" process can be carrided out by Nebula as follows:

```
nebula.sh unify --vcf <path to VCF files> --workdir <directory to store unified BED files>
```

This produces a set of unified VCF files for each sample. For instance `HG00514.merged_nonredundant.unified.all.vcf` includes all events on HG00514 while `HG00514.merged_nonredundant.unified.repeat.vcf` only includes events in repeat regions and `HG00514.merged_nonredundant.unified.vcf` includes only non-repeat events. Repeat events are identified by the presence of `IS_TRF=True` in the HGSV VCF files. We only used the non-repeat events for performance evaluation. It is preferable to pass BED files to Nebula as input. The VCF files can be converted to BED format using the `parse_vcf.py` script (note the `-` in arguments):

```
parse_vcf.py HG00514.merged_nonredundant.vcf - > HG00514.merged_nonredundant.bed
```

The other tools used in this study may require additional VCF fields not present in the data above, we have provided trivial values for those fields. There is a script that transforms the input VCF file for the required format for each tool. To convert a VCF file into Paragraph's required format run:

```
paragraphify_vcf.py HG00514.merged_nonredundant.unified.vcf
# outputs a file HG00514.merged_nonredundant.unified.paragraph.vcf
```

The VCF files for HG00514 and HG00733 need to be merged as most tools only accept a single VCF file for input (Nebula can take multiple BED files as input and will remove duplicates and merge overlapping events internally). The script `merge.sh` can be used for this purpose. It requires the presence of `HG00514.merged_nonredundant.unified.paragraph.vcf` and `HG00733.merged_nonredundant.unified.paragraph.vcf`. The scripts outputs two files `HG00514_HG00733.merged_nonredundant.unified.paragraph.sorted.DEL.vcf` with deletions and `HG00514_HG00733.merged_nonredundant.unified.paragraph.sorted.INS.vcf` with only insertions (the separation is necessary as Delly and SVTyper can't genotype insertions). These files can be used for all tools except BayesTyper.

## Inversions

For inversions we have a single VCF file that includes genotypes for all 9 samples in CHS, PUR and YRI trios (`HGSV_ILL.Integration.revise.20180208.vcf`). This file includes deletions and insertions as well as other SVs. To only get the inversions run:

```
grep -E "#|INV" HGSV_ILL.Integration.revise.20180208.vcf > HGSV_ILL.Integration.revise.20180208.INV.vcf
```

Run `parse_inv_vcf.py` on this file to get a set of BED files for each of the three samples:

```
./parse_inv_vcf.py HGSV_ILL.Integration.revise.20180208.INV.vcf
```

For the input to other tools, run the `paragraphify_vcf.py` script:

```
./paragraphify_vcf.py HGSV_ILL.Integration.revise.20180208.INV.vcf
```

The output can be used by SVtyper and Paragraph.

# Running

The sections below provide instruction on how to reproduce the results presented in the paper. We decided to include versions later in the study, as a result we had to repeat the whole procedure for inversions separately. Users trying to reproduce the results from scratch can include the inversions from the beginning and avoid the hassle of running the pipeline twice.

For the experiments presented in the manuscript, we will genotype the merged callset of events predicted on HG00514 and HG00733 on NA19240. However, in an attempt to remove possible false calls from the dataset, we only consider those events for the comparison that at least one of Delly, SVtyper or Paragraph can predict as present (other 1/0 or 1/1) on HG00514 or HG00733. To compute this "consensus" set of events, we need to run all genotypers on the base samples as well.

We ran the experiment in the following order:

1. Preprocess HG00514
2. Preprocess HG00733
3. Genotype the merged callset on NA19240 with Nebula
4. Run SVTyper, Delly, Paragraph and BayesTyper on NA19240
5. Run SVTyper, Delly and Paragraph on HG00514
6. Run SVTyper, Delly and Paragraph on HG00733
7. Calculate the consensus set of events
8. Compare results against Nebula on the consensus set

We have provided a skeleton directory structure for both the comparison and consensus stages. This skeleton includes scripts to perform the entire experiment. The scripts need to be modified with the actual path to their dependencies before running.

```
output/
    preprocessing/
        HG00514/
            Verifiction/
                BayesTyper/
                    kmc.sh
                    run.sh
                    genotype.sh
                    parse_vcf.py
                Paragraph/
                    DEL/
                        run.sh
                    INS/
                        run.sh
                    genotype_del.sh
                    genotype_ins.sh
                    parse_vcf.py
                SVtyper/
                    DEL/
                        run.sh
                    genotype_del.sh
                    parse_vcf.py
                Delly/
                    DEL/
                        run.sh
                    genotype_del.sh
                    parse_vcf.py
                consensus.sh
        HG00733/
            # same as HG00514
    genotyping/
        NA19240/
            DEL_INS/
                Verifiction/
                    run_delly.sh
                    run_svtyper.sh
                    run_paragraph.sh
                    run bayestyper.sh
                    consensus.sh
                    BayesTyper/
                        kmc.sh
                        run.sh
                        genotype.sh
                        parse_vcf.py
                    # otherwise similar to HG00514
```

## Nebula

Before running the preprocessing stage, one needs to extract kmers for GC content estimation. This stage selects kmers from different regions of the reference genome with different GC content levels. These kmers will be counted in the genotyping sample to provide better estimates of coverage across the genome. This need only be done once as the kmers are only dependent on the reference.

```
# Extract GC content esimtation kmers
nebula.sh gc --workdir output/preprocessing/GC_Kmers --reference GRC38.fasta --jellyfish hg38_mer_counts_32k.jf
```

Now we can preprocess HG00514 nad HG00733:

# For HG00514
nebula.sh preprocess --bed HG00514.unified.bed --reference GRC38.fasta --bam HG00514.alt_bwamem_GRCh38DH.20150715.CHS.high_coverage.bam --workdir output/preprocessing/HG00514 --jellyfish hg38_mer_counts_32k.jf --gckmers gc_kmers.json
nebula.sh genotype --bed HG00514.unified.bed --reference GRC38.fasta --bam HG00514.alt_bwamem_GRCh38DH.20150715.CHS.high_coverage.bam --workdir output/preprocessing/HG00514 --kmers output/preprocessing/HG00514/MixKmersJob/kmers.json --select
# HG00733
nebula.sh preprocess --bed HG00733.unified.bed --reference GRC38.fasta --bam HG00733.alt_bwamem_GRCh38DH.20150715.PUR.high_coverage.bam --workdir output/preprocessing/HG00733 --jellyfish hg38_mer_counts_32k.jf --gckmers gc_kmers.json
nebula.sh genotype --bed HG00733.unified.bed --reference GRC38.fasta --bam HG00733.alt_bwamem_GRCh38DH.20150715.PUR.high_coverage.bam --workdir output/preprocessing/HG00733 --kmers output/preprocessing/HG00733/MixKmersJob/kmers.json --select
```

This should take around 2 hours for each sample. We ran the inversion experiments during a later stage and separately, so we repeated the above steps for inversions. Alternatively, once can pass BED files for inversions along with the one for deletions and insertions and get the same results. This avoids the overhead of running the preprocessing for the same sample twice.

Once completed, the third sample can be genotyped. First (optionally) convert the downloaded BAM file for NA19240 into FASTQ using `bedtools bamtofastq`, then run:

```
nebula.sh genotype --bed HG00514.unified.bed HG00733.unified.bed --bam NA19240.alt_bwamem_GRCh38DH.20150715.YRI.high_coverage.fastq --workdir output/genotyping/NA19240/HG00514_HG00733 --kmers output/preprocessing/HG00514/ExportGenotypingKmersJob/kmers.json output/preprocessing/HG00733/ExportGenotypingKmersJob/kmers.json
```

Nebula is meant to be run on unmapped FASTQ files, however mapped BAM files are also accepted as input. Just use `--bam` instead of `--fastq`. Nebula will simply iterate over the BAM file and ignores all mapping information.

## BayesTyper

BayesTyper has a complex pipeline for selecting variants to genotype, however we are only inputting the unified 1KG variants here and the candidate selection pipeline can be skipped. BayesTyper needs to preprocess the input VCF file and requires KMC tables for genotyping. We use the same merged VCF file as before for deletion and insertions. BayesTyper significantly loses sensitivity with imprecise breakpoints, as a result we won't use it for consensus selection and only run it for comparison on NA19240.

First download the data bundle from [BayesTyper's Github repo](https://github.com/bioinformatics-centre/BayesTyper) for GRCh38. The bundle provides a set of SNP/CNV/SV calls that we won't use and reference assemblies for GRCh38 with decoy sequences. BayesTyper also depends on KMC so it should installed and added to `PATH`.

Navigate to `Verification/BayesTyper` for NA19240 and modify the `samples.tsv` file with the path to the BAM file for the sample, e.g:

```
NA19240	F	<path to NA19240.alt_bwamem_GRCh38DH.20150715.YRI.high_coverage.bam>
```

KMC requires a FASTQ file as input, so convert the BAM file into FASTQ using `bedtools bamtofastq` and update the `kmc.sh` script with the path to the FASTQ file and run it:

```
kmc -k55 -ci1 NA19240.alt_bwamem_GRCh38DH.20150715.YRI.high_coverage.Fq NA19240 ./KMC
bayesTyperTools makeBloom -k NA19240 -p 16
```

Update the `genotype.sh` script with the location of BayesTyper's reference assemblies and path to the merged VCF file and run it:

```
bayesTyperTools convertAllele -v HG00514_HG00733.merged_nonredundant.unified.paragraph.sorted.vcf -g BayesTyper/GRCh38.fa --keep-imprecise -o HG00514_HG00733.merged_nonredundant.unified.paragraph.sorted.bayestyper.vcf
bayesTyper cluster -v HG00514_HG00733.merged_nonredundant.unified.paragraph.sorted.bayestyper.vcf -s samples.tsv -g BayesTyper/GRCh38_canon.fa -d BayesTyper/GRCh38_decoy.fa -p 16
bayesTyper genotype -v bayestyper_unit_1/variant_clusters.bin -c bayestyper_cluster_data -s samples.tsv -g BayesTyper/GRCh38_canon.fa -d BayesTyper/GRCh38_decoy.fa -o bayestyper_unit_1/bayestyper -z -p 4 --disable-observed-kmers --noise-genotyping
```

This outputs a file named `bayestyper.vcf` in the directory `bayestyper_unit_1`. Copy the `run.sh` script into the `bayestyper_unit_1` directory and run it once genotyping is complete.

## Paragraph

Paragraph needs to be run on all three samples.

Move to the `Verification/Paragraph` directory for the current sample and update the `sample.txt` file with the path to the corresponding BAM file, e.g:

```
#id,path,depth,read length
NA19240,NA19240.alt_bwamem_GRCh38DH.20150715.YRI.high_coverage.bam,40,100
```

Update the `genotype_del.sh` or `genotype_ins.sh` scripts with the path to the specified VCF files and Paragraph's executable:

```
<path to multigrmpy.py> -r GRC38.fasta -i HG00514_HG00733.merged_nonredundant.unified.paragraph.sorted.DEL.vcf -m samples.txt -o ./DEL
```

This will genotype the events and output a files `genotypes.vcf.gz` under the `DEL` and `INS` directories. Run the `run.sh` script provided inside the `DEL` and `INS` directories once completed.

## SVTyper

SVtyper needs to be run on all three samples. Note that SVTyper does not support insertions.

Navigate to the `Verficiation/SVtyper` and modify the `genotype_del.sh` script with the proper path to the BAM file and the specified VCF file for the current experiment:

```
svtyper -i HG00514_HG00733.merged_nonredundant.unified.paragraph.sorted.DEL.vcf -B NA19240.alt_bwamem_GRCh38DH.20150715.YRI.high_coverage.bam > DEL/genotypes.vcf
```

The script output a file `genotypes.vcf` in the `DEL` directory. Execute the `run.sh` script provided inside the `DEL` directory once completed.

## Delly

Delly needs to be run on all three samples. Note that Delly does not support insertions.

Delly requires a GRCh38 reference with decoy sequences (we can use the one from BayesTyper's bundle) and a file with regions to be exluded (provided in the skeleton). Navigate to `Verification/Delly` for the current sample and update `genotype_del.sh` with path to the reference assembly and BAM and VCF files as below:

```
delly call -g GRCh38_decoys.fa -v HG00514_HG00733.merged_nonredundant.unified.paragraph.sorted.DEL.vcf -x human.hg38.excl -o ./DEL/genotypes.bcf NA19240.alt_bwamem_GRCh38DH.20150715.YRI.high_coverage.bam
```

Delly outputs a `BCF` files in the `DEL` directory that needs to be converted to `VCF`, so the latest vrsion of `bcftools` is required. Naviagte to the `DEL` directory and invoke the `run.sh` script once completed.

# Validation

Nebula outputs a file named `merge.bed` under the directory `CgcIntegerProgrammingJob` inside the specified `wokdir` with genotypes for the sample. To compare Nebula's results against actual NA19240 predictions run:

```
tabulate.sh merge.bed
verify.sh NA19240.unified.bed
```

This creates several files:

```
00_as_00.bed
00_as_10.bed
00_as_11.bed
10_as_00.bed
10_as_10.bed
10_as_11.bed
11_as_00.bed
11_as_10.bed
11_as_11.bed
```

With 3 genotypes of 0/0, 0/1 and 1/1, there are 9 possibilities for each prediction (e.g a 0/0 event being predicted as 1/0, etc). Each file above contains the events falling in one of these 9 categories.

To compare Nebula's results with those of another tool on NA19240, run the corresponding script such as `run_paragraph.sh` provided inside the `Verification` directory with the path to `NA19240.unified.bed` as an argument. This will output tables for the genotyping performance of each tool.

[1]: https://www.nature.com/articles/s41467-018-08148-z
