from __future__ import print_function

import io
import os
import re
import pwd
import sys
import copy
import json
import math
import time
import argparse
import operator
import traceback
import subprocess

from itertools import chain

from nebula import (
    bed,
    config,
    gapped,
    counter,
    reduction,
    map_reduce,
    statistics,
    visualizer,
)

import pysam

from nebula.kmers import *
from nebula.commons import *
from nebula.chromosomes import *
print = pretty_print

# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #

class ExtractJunctionKmersJob(map_reduce.Job):

    _name = 'ExtractJunctionKmersJob'
    _category = 'preprocessing'
    _previous_job = None

    # ============================================================================================================================ #
    # Launcher
    # ============================================================================================================================ #

    @staticmethod
    def launch(**kwargs):
        job = ExtractJunctionKmersJob(**kwargs)
        job.execute()

    # ============================================================================================================================ #
    # MapReduce overrides
    # ============================================================================================================================ #

    def execute(self):
        c = config.Configuration()
        self.pre_process()
        self.create_output_directories()
        self.find_thread_count()
        self.prepare()
        self.load_inputs()

    def load_inputs(self):
        c = config.Configuration()
        self.contigs = pysam.AlignmentFile(c.contigs, "rb")
        self.alignments = pysam.AlignmentFile(c.bam, "rb")
        self.tracks = c.tracks
        self.extract_kmers()
        self.num_threads = 1

    def extract_kmers(self):
        c = config.Configuration()
        contig_index = {}
        output = {}
        for track in self.tracks:
            contig_index[self.tracks[track].contig] = self.tracks[track]
        n = 0
        print(len(contig_index), 'total tracks')
        for read in self.contigs.fetch():
            if read.query_name in contig_index:
                t = contig_index[read.query_name]
                kmers = {}
                kmers.update(self.extract_assembly_kmers(t, read.query_sequence))
                kmers.update(self.extract_mapping_kmers(t))
                if len(kmers) > 0:
                    path = os.path.join(self.get_current_job_directory(), t.id + '.json')
                    with open(path, 'w') as json_file:
                        json.dump(kmers, json_file, indent = 4)
                    output[t.id] = path
                    n += 1
                if n % 1000 == 0:
                    print(n)
        with open(os.path.join(self.get_current_job_directory(), 'batch_merge.json'), 'w') as json_file:
            json.dump(output, json_file, indent = 4)

    def extract_assembly_kmers(self, track, assembly):
        c = config.Configuration()
        junction_kmers = {}
        if track.svtype == 'DEL':
            l = list(range(int(track.contig_start) - 24, int(track.contig_start) - 8))
        if track.svtype == 'INS':
            l = list(range(int(track.contig_start) - 24, int(track.contig_start) - 8)) + list(range(int(track.contig_end) - 24, int(track.contig_end) - 8))
        for i in l:
            kmer = canonicalize(assembly[i: i + c.ksize])
            if not kmer in junction_kmers:
                junction_kmers[kmer] = {
                    'count': 0,
                    'source': 'assembly',
                    'loci': {
                        'junction_' + track.id: {
                            'masks': {
                                'left': assembly[i - c.ksize: i],
                                'right': assembly[i + c.ksize: i + c.ksize + c.ksize]
                            }
                        }
                    }
                }
            junction_kmers[kmer]['count'] += 1
        junction_kmers = {kmer: junction_kmers[kmer] for kmer in junction_kmers if junction_kmers[kmer]['count'] == 1}
        return junction_kmers

    def extract_mapping_kmers(self, track):
        c = config.Configuration()
        junction_kmers = {}
        slack = 100
        stride = c.ksize
        # may file to fine associated contig in mapping
        try:
            if track.svtype == 'DEL':
                reads = chain(self.alignments.fetch(track.chrom, track.begin - slack, track.begin + slack), self.alignments.fetch(track.chrom, track.end - slack, track.end + slack))
            if track.svtype == 'INS':
                reads = self.alignments.fetch(track.chrom, track.begin - slack, track.begin + slack)
        except:
            return {}
        n = 0
        for read in reads:
            n += 1
            if read.query_alignment_length != len(read.query_sequence): # not everything was mapped
                seq = read.query_sequence
                if read.reference_start >= track.begin - slack and read.reference_start <= track.end + slack:
                    cigartuples = read.cigartuples
                    clips = []
                    offset = 0
                    for cigar in cigartuples:
                        if cigar[0] == 4: #soft clip
                            clips.append((offset, offset + cigar[1]))
                        offset += cigar[1]
                    index = 0
                    # Should try and correct for sequencing errors in masks by doing a consensus
                    for kmer in stream_kmers(c.ksize, True, True, seq):
                        if self.is_clipped((index, index + c.ksize), clips):
                            locus = 'junction_' + track.id
                            if not kmer in junction_kmers:
                                junction_kmers[kmer] = {
                                    'count': 0,
                                    'source': 'mapping',
                                    'loci': {
                                        locus: {
                                            'masks': {
                                                'left': None,
                                                'right': None
                                            }
                                        }
                                    }
                                }
                            if len(seq[index - c.ksize: index]) == c.ksize:
                                junction_kmers[kmer]['loci'][locus]['masks']['left'] = seq[index - c.ksize: index]
                            if len(seq[index + c.ksize: index + c.ksize + c.ksize]) == c.ksize:
                                junction_kmers[kmer]['loci'][locus]['masks']['right'] = seq[index + c.ksize: index + c.ksize + c.ksize]
                            junction_kmers[kmer]['count'] += 1
                        index += 1
        _junction_kmers = {} 
        for kmer in junction_kmers:
            if junction_kmers[kmer]['count'] >= 3 and junction_kmers[kmer]['loci']['junction_' + track.id]['masks']['right'] and junction_kmers[kmer]['loci']['junction_' + track.id]['masks']['left']:
                _junction_kmers[kmer] = junction_kmers[kmer]
        return _junction_kmers

    def is_clipped(self, kmer, clips):
        for clip in clips:
            if self.overlap(kmer, clip) >= 0 and self.overlap(kmer, clip) >= 10:
                return True
        return False

    def overlap(self, a, b):
        return max(0, min(a[1], b[1]) - max(a[0], b[0]))

# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #

class UniqueJunctionKmersJob(map_reduce.Job):

    _name = 'UniqueJunctionKmersJob'
    _category = 'preprocessing'
    _previous_job = ExtractJunctionKmersJob

    # ============================================================================================================================ #
    # Launcher
    # ============================================================================================================================ #

    @staticmethod
    def launch(**kwargs):
        job = UniqueJunctionKmersJob(**kwargs)
        job.execute()

    def load_inputs(self):
        c = config.Configuration()
        self.junction_kmers = {} 
        tracks = self.load_previous_job_results()
        for track in tracks:
            with open(os.path.join(self.get_previous_job_directory(), tracks[track]), 'r') as json_file:
                junction_kmers = json.load(json_file)
                for kmer in junction_kmers:
                    k = canonicalize(kmer)
                    if not k in self.junction_kmers:
                        self.junction_kmers[k] = copy.deepcopy(junction_kmers[kmer])
                        self.junction_kmers[k]['loci'] = {}
                        self.junction_kmers[k]['tracks'] = {}
                    if not track in self.junction_kmers[k]['tracks']:
                        self.junction_kmers[k]['loci'].update(junction_kmers[kmer]['loci'])
                        self.junction_kmers[k]['tracks'][track] = 0
                    self.junction_kmers[k]['tracks'][track] += 1
        self.round_robin(tracks)

    def transform(self, track, track_name):
        c = config.Configuration()
        with open(os.path.join(self.get_previous_job_directory(), track), 'r') as json_file:
            junction_kmers = json.load(json_file)
        junction_kmers = {canonicalize(kmer): self.junction_kmers[canonicalize(kmer)] for kmer in junction_kmers if 'N' not in kmer}
        path = os.path.join(self.get_current_job_directory(), track_name  + '.json')
        with open(path, 'w') as json_file:
            json.dump(junction_kmers, json_file, sort_keys = True, indent = 4)
        return track_name + '.json'

# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #

class JunctionKmersScoringJob(gapped.UniqueGappedKmersScoringJob):

    _name = 'JunctionKmersScoringJob'
    _category = 'preprocessing'
    _previous_job = UniqueJunctionKmersJob

    # ============================================================================================================================ #
    # Launcher
    # ============================================================================================================================ #

    @staticmethod
    def launch(**kwargs):
        job = JunctionKmersScoringJob(**kwargs)
        job.execute()

    def transform(self, sequence, chrom):
        c = config.Configuration()
        t = time.time()
        l = len(sequence)
        for index in range(0, l - 100):
            if index % 100000 == 1:
                s = time.time()
                p = index / float(len(sequence))
                e = (1.0 - p) * (((1.0 / p) * (s - t)) / 3600)
                print('{:5}'.format(chrom), 'progress:', '{:12.10f}'.format(p), 'took:', '{:14.10f}'.format(s - t), 'ETA:', '{:12.10f}'.format(e))
            half_mer = sequence[index: index + c.hsize]
            if not half_mer in self.half_mers:
                continue
            for k in range(32, 32 + 1):
                kmer = canonicalize(sequence[index: index + k])
                kmer = kmer[:c.hsize] + kmer[-c.hsize:]
                if kmer in self.kmers:
                    self.kmers[kmer]['count'] += 1
                    self.kmers[kmer]['loci'][chrom + '_' + str(index)] = {
                            'masks': {
                                'left': sequence[index - c.ksize: index],
                                'right': sequence[index + k: index + k + c.ksize]
                            }
                        }

# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #

class FilterJunctionKmersJob(reduction.FilterLociIndicatorKmersJob):

    # ============================================================================================================================ #
    # Launcher
    # ============================================================================================================================ #

    _name = 'FilterJunctionKmersJob'
    _category = 'preprocessing'
    _previous_job = JunctionKmersScoringJob 

    @staticmethod
    def launch(**kwargs):
        job = FilterJunctionKmersJob(**kwargs)
        job.execute()

    # ============================================================================================================================ #
    # MapReduce overrides
    # ============================================================================================================================ #

    def load_inputs(self):
        c = config.Configuration()
        self.kmers = {}
        self.tracks = self.load_previous_job_results()
        self.round_robin(self.tracks)
        print('filtering', len(self.tracks), 'tracks')

    def transform(self, track, track_name):
        with open(os.path.join(self.get_previous_job_directory(), track), 'r') as json_file:
            kmers = json.load(json_file)
            for kmer in kmers:
                if kmers[kmer]['count'] <= 3:
                    interest_kmers = {}
                    self.kmers[kmer] = {}
                    self.kmers[kmer]['loci'] = kmers[kmer]['loci']
                    self.kmers[kmer]['total'] = 0
                    self.kmers[kmer]['count'] = 0
                    self.kmers[kmer]['doubt'] = 0
                    self.kmers[kmer]['source'] = kmers[kmer]['source']
                    self.kmers[kmer]['tracks'] = kmers[kmer]['tracks']
                    self.kmers[kmer]['reference'] = kmers[kmer]['count']
                    self.kmers[kmer]['interest_masks'] = {}
                    for locus in self.kmers[kmer]['loci']:
                        self.kmers[kmer]['loci'][locus]['masks'] = {self.kmers[kmer]['loci'][locus]['masks']['left']: True, self.kmers[kmer]['loci'][locus]['masks']['right']: True}
                    for locus in self.kmers[kmer]['loci']:
                        if 'junction_' in locus:
                            self.kmers[kmer]['interest_masks'].update(self.kmers[kmer]['loci'][locus]['masks'])
            return None

    def is_kmer_returning(self, kmer):
        c = config.Configuration()
        for track in kmer['tracks']:
            t = c.tracks[track]
            for loci in kmer['loci']:
                if not 'junction' in loci:
                    start = int(loci.split('_')[1])
                    if abs(start - t.begin) < 2 * c.ksize:
                        return True
                    if abs(start - t.end) < 2 * c.ksize:
                        return True
        return False

    def output_batch(self, batch):
        remove = {}
        for kmer in self.kmers:
            for locus in self.kmers[kmer]['loci'].keys():
                l = self.get_shared_masks(self.kmers[kmer]['interest_masks'], self.kmers[kmer]['loci'][locus]['masks'])
                if l == 0:
                    self.kmers[kmer]['loci'].pop(locus, None)
            self.kmers[kmer].pop('interest_masks', None)
        json_file = open(os.path.join(self.get_current_job_directory(), 'batch_' + str(self.index) + '.json'), 'w')
        json.dump(self.kmers, json_file, sort_keys = True, indent = 4)
        json_file.close()
        exit()

    def reduce(self):
        self.kmers = {}
        for batch in self.load_output():
            for kmer in batch:
                self.kmers[kmer] = batch[kmer]
        #
        print(len(self.kmers), 'kmers')
        returning_kmers = {kmer: self.kmers[kmer] for kmer in self.kmers if self.is_kmer_returning(self.kmers[kmer])}
        with open(os.path.join(self.get_current_job_directory(), 'returning.json'), 'w') as json_file:
            json.dump(returning_kmers, json_file, indent = 4)
        self.kmers = {kmer: self.kmers[kmer] for kmer in self.kmers if not self.is_kmer_returning(self.kmers[kmer])}
        print(len(self.kmers), 'kmers after filtering returning kmers')
        with open(os.path.join(self.get_current_job_directory(), 'kmers.json'), 'w') as json_file:
            json.dump(self.kmers, json_file, indent = 4, sort_keys = True)
        self.tracks = {}
        for kmer in self.kmers:
            for track in self.kmers[kmer]['tracks']:
                if not track in self.tracks:
                    self.tracks[track] = {}
                self.tracks[track][kmer] = self.kmers[kmer]
        print(len(self.tracks))
        #visualizer.histogram(list(map(lambda kmer: len(self.kmers[kmer]['loci']), self.kmers)), 'number_of_loci', self.get_current_job_directory(), 'number of loci', 'number of kmers')
        #print(len(self.tracks))
        for track in self.tracks:
            with open(os.path.join(self.get_current_job_directory(), track + '.json'), 'w') as json_file:
                json.dump(self.tracks[track], json_file, indent = 4)

# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
