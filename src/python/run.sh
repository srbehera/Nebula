cd /share/hormozdiarilab/Codes/NebulousSerendipity
source venv/bin/activate
cd ./src/python
python -m kmer.prune --fastq /share/hormozdiarilab/Data/Genomes/Illumina/CHMs/CHM1_hg38/CHM1.samtoolsversion.fq --threads 12
python -m kmer.break_point --coverage 30 --std 20
