import os
import pwd
import sys

from . import (
    reference,
)

import colorama

# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #

class Configuration:

    kmer_cache_size = 10000

    class __impl:
        def __init__(self, ksize, khmer_table_size, khmer_num_tables,\
                fastq_file, bed_file, output_directory, num_threads):
            self.ksize = ksize
            self.khmer_table_size = khmer_table_size
            self.khmer_num_tables = khmer_num_tables
            self.fastq_file = fastq_file
            self.bed_file = bed_file
            self.output_directory = output_directory
            self.num_threads = num_threads

        def kmer_size(self):
            return self.ksize

    __instance = None

    def __init__(self, ksize=None, khmer_table_size=None, khmer_num_tables=None,\
            fastq_file=None, bed_file=None, output_directory=None, num_threads=None):
        if Configuration.__instance is None:
            Configuration.__instance = Configuration.__impl(ksize, khmer_table_size,\
                khmer_num_tables, fastq_file, bed_file, output_directory, num_threads)

    def __getattr__(self, attr):
        return getattr(self.__instance, attr)

    def __setattr__(self, attr, value):
        return setattr(self.__instance, attr, value)

# ============================================================================================================================ #
# Configuration
# ============================================================================================================================ #

def configure():
    if sys.platform == "darwin":
        print('Running on Mac OS X')
        khmer_table_size = 16e7
        khmer_num_tables = 4
        reference.ReferenceGenome(os.path.abspath(os.path.join(os.path.dirname(__file__),\
            '../../../data/hg38.fa')))
        fastq_file = os.path.abspath(os.path.join(os.path.dirname(__file__),\
            '../../../data/CHM1.samtoolsversion.head.small.fq'))
        num_threads = 1
    else:
        print('Running on Linux')
        khmer_table_size = 16e9
        khmer_num_tables = 4
        fastq_file = '/share/hormozdiarilab/Data/Genomes/Illumina/CHMs/CHM1_hg38/CHM1.samtoolsversion.fq'
        reference.ReferenceGenome('/share/hormozdiarilab/Data/ReferenceGenomes/Hg19/hg19.ref')
        num_threads = 48
    Configuration(
        ksize = 31,
        khmer_table_size = khmer_table_size,
        khmer_num_tables = khmer_num_tables,
        fastq_file = fastq_file,
        bed_file = os.path.abspath(os.path.join(os.path.dirname(__file__),\
            '../../../data/CHM1_Lumpy.Del.100bp.bed')),
            # '../../../data/variations.bed')),
        output_directory = os.path.abspath(os.path.join(os.path.dirname(__file__),\
            '../../../output')),
        num_threads = num_threads
    )
    colorama.init()
 