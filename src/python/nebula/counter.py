from __future__ import print_function

import io
import os
import re
import pwd
import sys
import copy
import json
import time
import argparse
import operator
import traceback
import subprocess

from nebula import (
    bed,
    config,
    map_reduce,
)

from nebula.kmers import *
from nebula.commons import *
print = pretty_print

# ============================================================================================================================ #
# ============================================================================================================================ #
# MapReduce Job to find reads containing kmers from structural variation events that produce too many novel kmers.
# ============================================================================================================================ #
# ============================================================================================================================ #

class BaseExactCountingJob(map_reduce.Job):

    # ============================================================================================================================ #
    # MapReduce overrides
    # ============================================================================================================================ #

    def find_thread_count(self):
        c = config.Configuration()
        self.num_threads = 1 if c.bam else min(4, c.threads)

    def round_robin(self):
        for i in range(0, self.num_threads):
            self.batch[i] = {}

    def run_batch(self, batch):
        c = config.Configuration()
        self.transform()

    def export_accelerator_input(self):
        pass

    def transform(self):
        #print('here')
        c = config.Configuration()
        cpp_dir = os.path.join(os.path.dirname(__file__), '../../cpp')
        if c.simulation:
            for i in range(1, 2 + 1):
                #fastq_file = os.path.join(self.get_simulation_directory(), 'test.' + str(i) + '.fq')
                fastq_file = os.path.join(self.get_simulation_directory(), 'chr17_diploid.' + str(i) + '.fq')
                #fastq_file = "/share/hormozdiarilab/Codes/NebulousSerendipity/output/simulation/HG00513.hg19.chr17.DEL.bed/Seed1300SnpError0.001/20x/Simulation/reads.sorted.bam"
                print(yellow(fastq_file))
                command = os.path.join(cpp_dir, "counter.out") + " " + str(self.index) + " " + self.get_current_job_directory() +  " " + fastq_file + " " + str(self.num_threads) + " " + str(self._counter_mode) + " " + ("1" if c.debug else "0") + " " + ("1" if c.simulation else "0")
                print(command)
                output = subprocess.call(command, shell = True)
                command = "mv " + os.path.join(self.get_current_job_directory(), 'c_batch_' + str(self.index) + '.json') + " " + os.path.join(self.get_current_job_directory(), 'c_batch_' + str(self.index) + '.' + str(i) + '.json')
                print(command)
                output = subprocess.call(command, shell = True)
        else:
            reads_file = c.fastq if c.fastq else c.bam
            print(yellow(reads_file))
            command = os.path.join(cpp_dir, "counter.out") + " " + str(self.index) + " " + self.get_current_job_directory() +  " " + reads_file + " " + str(self.num_threads) + " " + str(self._counter_mode) + " " + ("1" if c.debug else "0") + " " + ("1" if c.simulation else "0")
            print(command)
            output = subprocess.call(command, shell = True)
        exit()

    def merge_count(self, kmer, tokens):
        pass

    def merge_counts(self):
        c = config.Configuration()
        for i in range(0, self.num_threads):
            if c.simulation:
                paths = [os.path.join(self.get_current_job_directory(), 'c_batch_' + str(i) + '.1.json'), os.path.join(self.get_current_job_directory(), 'c_batch_' + str(i) + '.2.json')]
            else:
                paths = [os.path.join(self.get_current_job_directory(), 'c_batch_' + str(i) + '.json')]
            print('adding batch', i)
            for path in paths:
                print(path)
                with open (path, 'r') as json_file:
                    line = json_file.readline()
                    while line:
                        tokens = line.split(':')
                        self.merge_count(tokens[0], [int(t) for t in tokens[1:]])
                        line = json_file.readline()
