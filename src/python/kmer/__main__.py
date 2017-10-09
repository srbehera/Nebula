import os
import pwd
from sys import platform

from . import (
    bed,
    reference,
    config
)

if __name__ == '__main__':
    print('cwd: {}'.format(os.getcwd()))
    khmer_table_size = 5e8
    khmer_num_tables = 4
    if platform == "darwin":
        print('Running on Mac OS X')
        reference.ReferenceGenome(os.path.abspath(os.path.join(os.path.dirname(__file__),
            '../../../data/hg38.fa')))
        fastq_file = os.path.abspath(os.path.join(os.path.dirname(__file__),\
            '../../../data/CHM1.samtoolsversion.head.tiny.fq'))
    else:
        print('Running on Linux')
        reference.ReferenceGenome('/share/hormozdiarilab/Data/ReferenceGenomes/Hg38/hg38.fa')
        fastq_file = '/share/hormozdiarilab/Data/Genomes/Illumina/CHMs/CHM1_hg38/CHM1.samtoolsversion.fq'
    config.Configuration(
        ksize = 25,
        khmer_table_size = khmer_table_size,
        khmer_num_tables = khmer_num_tables,
        fastq_file = fastq_file,
        bed_file = os.path.abspath(os.path.join(os.path.dirname(__file__),\
            '../../../data/CHM1.inversions_hg38.bed'))
    )
    bed.read_tracks_from_bed_file()
