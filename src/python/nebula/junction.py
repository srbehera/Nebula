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

from difflib import SequenceMatcher
from itertools import chain

from nebula import (
    bed,
    config,
    counter,
    reduction,
    map_reduce,
    statistics,
    visualizer,
)

from nebula.debug import *
from nebula.kmers import *
from nebula.logger import *
from nebula.chromosomes import *

import pysam

import numpy as np

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

    def load_inputs(self):
        c = config.Configuration()
        self.contigs = pysam.AlignmentFile(c.contigs, "rb") if c.contigs else None
        self.alignments = pysam.AlignmentFile(c.bam, "rb")
        self.tracks = c.tracks
        self.chroms = extract_whole_genome()
        self.round_robin(self.tracks)

    def transform(self, track, track_name):
        if abs(int(track.svlen)) < 50:
            return None
        #if track_name != 'DEL@chr1_6858655_6858832':
        #    return None
        #if track_name != 'DEL@chr2_11065564_11065676':
        #    return None
        c = config.Configuration()
        self.alignments = pysam.AlignmentFile(c.bam, "rb")
        kmers = self.extract_mapping_kmers(track)
        if len(kmers) > 0:
            path = os.path.join(self.get_current_job_directory(), track_name + '.json')
            with open(path, 'w') as json_file:
                json.dump(kmers, json_file, indent = 4)
            return path
        else:
            system_print_warning('No junction kmers found for ' + track_name + '.')
            return None

    def calculate_average_read_quality(self, read):
        q = read.query_qualities

    def extract_mapping_kmers(self, track):
        c = config.Configuration()
        junction_kmers = {}
        slack = c.read_length
        stride = c.ksize
        try:
            # Events that alter or remove a part of the reference
            if track.svtype == 'DEL' or track.svtype == 'INV':
                reads = chain(self.alignments.fetch(track.chrom, track.begin - 1 * slack, track.begin + 1 * slack), self.alignments.fetch(track.chrom, track.end - 1 * slack, track.end + 1 * slack))
            # Events that add sequence that wasn't there
            if track.svtype == 'INS' or track.svtype == 'ALU' or track.svtype == 'MEI':
                reads = self.alignments.fetch(track.chrom, track.begin - 1 * slack, track.begin + 1 * slack)
        except:
            return {}
        #_reads = []
        #pair_map = {}
        #if c.filter_overlapping_pairs:
        #    for read in reads:
        #        if read.qname not in pair_map:
        #            if not read.is_paired or read.mate_is_unmapped or read.is_unmapped:
        #                _reads.append(read)
        #            else:
        #                pair_map[read.qname] = read
        #        else:
        #            if abs(read.reference_start - pair_map[read.qname].reference_end) < 10 or \
        #                abs(pair_map[read.qname].reference_start - read.reference_end) < 10:
        #                    pair_map.pop(read.qname, None)
        #                    continue
        #            else:
        #                _reads.append(read)
        #                _reads.append(pair_map[read.qname])
        #print('Remaining', len(pair_map))
        #for qname in pair_map:
        #    _reads.append(pair_map[qname])
        #print('Processing ', len(_reads), 'reads..')
        n = 0
        for read in reads:
            #if read.qname != 'H2YHMBCXX:17:8:564672:0':
            #if read.qname != 'H2YHMBCXX:32:10:2827708:0':
            #    continue
            #print('---------------------------------------------')
            #print(read.qname)
            # These MAPQ scores vary from aligner to aligner but < 5 should be bad enough anywhere
            # if read.mapping_quality <= 5:
            #    system_print_warning('Skipping read low mapping quality.')
            #    continue
            #TODO: figure out why
            #if not read.cigartuples:
            #    print(read.query_sequence)
            #    print(read.query_alignment_length, len(read.query_sequence))
            if read.query_alignment_length == len(read.query_sequence): # not everything was mapped
                continue
            if read.reference_start >= track.begin - slack and read.reference_start <= track.end + slack:
                n += 1
                clips = []
                offset = 0
                deletions = []
                insertions = []
                i = 0
                left_clipped = False
                right_clipped = False
                for cigar in read.cigartuples:
                    if cigar[0] == 4: #soft clip
                        if i == 0:
                            left_clipped = True
                        else:
                            right_clipped = True
                        clips.append((offset, offset + cigar[1]))
                    if cigar[0] == 2: #deletion
                        if cigar[1] >= abs(int(track.svlen)) * 0.9 and cigar[1] <= abs(int(track.svlen)) * 1.1:
                            deletions.append((offset, offset + cigar[1]))
                    if cigar[0] == 1: #insertion
                        if cigar[1] >= abs(int(track.svlen)) * 0.9 and cigar[1] <= abs(int(track.svlen)) * 1.1:
                            insertions.append((offset, offset + cigar[1]))
                    offset += cigar[1]
                    i += 1
                #TODO Should try and correct for sequencing errors in masks by doing a consensus
                seq = read.query_sequence
                index = 0
                for kmer in stream_kmers(c.ksize, True, True, seq):
                    if 'N' in kmer:
                        index += 1
                        continue
                    b = self.is_clipped(track, (index, index + c.ksize), read, clips, deletions, insertions, right_clipped, left_clipped) 
                    if b:
                        #print('Selecting', kmer)
                        locus = 'junction_' + track.id
                        if not kmer in junction_kmers:
                            junction_kmers[kmer] = {
                                'count': 0,
                                'source': b,
                                'loci': {
                                    locus: {
                                        'masks': {}
                                        }
                                },
                                'read': {
                                    'end': read.reference_end,
                                    'start': read.reference_start,
                                    'qname': read.qname
                                },
                            }
                            if len(seq[index - c.ksize: index]) == c.ksize:
                                junction_kmers[kmer]['loci'][locus]['masks']['left'] = seq[index - c.ksize: index]
                            if len(seq[index + c.ksize: index + c.ksize + c.ksize]) == c.ksize:
                                junction_kmers[kmer]['loci'][locus]['masks']['right'] = seq[index + c.ksize: index + c.ksize + c.ksize]
                        junction_kmers[kmer]['count'] += 1
                    index += 1
        #print("Found", n, "reads.")
        #incomplete_kmers = {kmer: junction_kmers[kmer] for kmer in junction_kmers if len(junction_kmers[kmer]['loci'][locus]['masks']) != 2}
        _junction_kmers = {}
        for kmer in junction_kmers:
            if junction_kmers[kmer]['count'] >= min(3, c.coverage / 4):
                _junction_kmers[kmer] = junction_kmers[kmer]
        return _junction_kmers

    def approx_equal(self, a, b):
        required_edits = [code for code in (SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes()) if code[0] != 'equal']
        return len(required_edits) <= 3

    #TODO: Is this a mistake?
    def is_clipped(self, track, kmer, read, clips, deletions, insertions, right_clipped, left_clipped):
        for i, clip in enumerate(clips):
            if self.overlap(kmer, clip) >= 0 and self.overlap(kmer, clip) >= 10:
                if i == 0 and left_clipped:
                    # kmer[0] < clip[1] always
                    assert kmer[0] <= clip[1]
                    ref_index = read.reference_start - (clip[1] - kmer[0])
                    ref_sequence = chroms[track.chrom][ref_index: ref_index + 32]
                    kmer_seq = read.query_sequence[kmer[0]: kmer[0] + 32]
                    #print('Left', kmer_seq, ' = ', ref_sequence, self.approx_equal(kmer_seq, ref_sequence))
                    if self.approx_equal(kmer_seq, ref_sequence):
                        return None
                elif i == 0 and right_clipped:
                    # kmer[1] > clip[0] always
                    assert kmer[1] >= clip[0]
                    ref_index = read.reference_end + (kmer[1] - clip[0])
                    ref_sequence = chroms[track.chrom][ref_index - 32: ref_index]
                    kmer_seq = read.query_sequence[kmer[0]: kmer[0] + 32]
                    #print('Left', kmer_seq, ' = ', ref_sequence, self.approx_equal(kmer_seq, ref_sequence))
                    if self.approx_equal(kmer_seq, ref_sequence):
                        return None
                elif i == 1 and right_clipped:
                    assert kmer[1] >= clip[0]
                    ref_index = read.reference_end + (kmer[1] - clip[0])
                    ref_sequence = chroms[track.chrom][ref_index - 32: ref_index]
                    kmer_seq = read.query_sequence[kmer[0]: kmer[0] + 32]
                    #print('Right', kmer_seq, ' = ', ref_sequence, self.approx_equal(kmer_seq, ref_sequence))
                    if self.approx_equal(kmer_seq, ref_sequence):
                        return None
                else:
                    #print(i, clips, right_clipped, left_clipped)
                    assert False
                return 'junction'
        for clip in deletions:
            if self.overlap(kmer, clip) >= 0 and self.overlap(kmer, clip) >= 10:
                return 'deletion'
        for clip in insertions:
            if self.overlap(kmer, clip) >= 0 and self.overlap(kmer, clip) >= 10:
                return 'insertion'
        return False

    def overlap(self, a, b):
        return max(0, min(a[1], b[1]) - max(a[0], b[0]))

    def reduce(self):
        c = config.Configuration()
        map_reduce.Job.reduce(self)
        #return None
        cpp_dir = os.path.join(os.path.dirname(__file__), '../../cpp/scanner')
        command = os.path.join(cpp_dir, "scanner.out") + " " + c.reference + " " + self.get_output_directory() +  " " + str(24)
        print(command)
        output = subprocess.call(command, shell = True)

# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #

class ScoreJunctionKmersJob(map_reduce.Job):

    _name = 'ScoreJunctionKmersJob'
    _category = 'preprocessing'
    _previous_job = ExtractJunctionKmersJob

    # ============================================================================================================================ #
    # Launcher
    # ============================================================================================================================ #

    @staticmethod
    def launch(**kwargs):
        job = ScoreJunctionKmersJob(**kwargs)
        job.execute()

    # ============================================================================================================================ #
    # MapReduce overrides
    # ============================================================================================================================ #

    def load_inputs(self):
        c = config.Configuration()
        self.kmers = {}
        self.tracks = self.load_previous_job_results()
        n = 0
        for track in self.tracks:
            kmers = json.load(open(self.tracks[track]))
            n += 1
            for kmer in kmers:
                k = canonicalize(kmer)
                if not k in self.kmers:
                    self.kmers[k] = copy.deepcopy(kmers[kmer])
                    self.kmers[k]['loci'] = {}
                    # keeps track of reference loci
                    self.kmers[k]['count'] = 0
                    self.kmers[k]['tracks'] = {}
                    # legacy
                    self.kmers[k].pop('read', None)
                    self.kmers[k].pop('reads', None)
                self.kmers[k]['loci'].update(kmers[kmer]['loci'])
                self.kmers[k]['tracks'][track] = 1
            if n % 100 == 0:
                print('Loaded', n, 'out of', len(self.tracks), 'tracks')
        system_print_high('Scanning for', len(self.kmers), 'kmers..')
        #launch_scanner()
        #exit()
        self.chroms = extract_whole_genome()
        self.round_robin(self.chroms)

    def transform(self, sequence, chrom):
        c = config.Configuration()
        t = time.time()
        l = len(sequence)
        for index in range(0, l - 100):
            kmer = canonicalize(sequence[index: index + c.ksize])
            if kmer in self.kmers:
                self.kmers[kmer]['count'] += 1
                self.kmers[kmer]['loci'][chrom + '_' + str(index)] = {
                    'masks': {
                        'left': sequence[index - c.ksize: index],
                        'right': sequence[index + c.ksize: index + c.ksize + c.ksize]
                    }
                }
            if index % 1000000 == 1:
                s = time.time()
                p = index / float(len(sequence))
                e = (1.0 - p) * (((1.0 / p) * (s - t)) / 3600)
                system_print('{:5}'.format(chrom), 'progress:', '{:12.10f}'.format(p), 'took:', '{:14.10f}'.format(s - t), 'ETA:', '{:12.10f}'.format(e))

    def output_batch(self, batch):
        json_file = open(os.path.join(self.get_current_job_directory(), 'batch_' + str(self.index) + '.json'), 'w')
        json.dump(self.kmers, json_file, sort_keys = True, indent = 4)
        json_file.close()

    def merge_counts(self):
        c = config.Configuration()
        system_print_normal('Merging reference counts..')
        for batch in self.load_output():
            for kmer in batch:
                if not kmer in self.kmers:
                    continue
                self.kmers[kmer]['count'] += batch[kmer]['count']
                if 'loci' in batch[kmer]:
                    self.kmers[kmer]['loci'].update(batch[kmer]['loci'])

    def reduce(self):
        self.merge_counts()
        self.tracks = {}
        n = 0
        for kmer in self.kmers:
            for track in self.kmers[kmer]['tracks']:
                if not track in self.tracks:
                    self.tracks[track] = {}
                self.tracks[track][kmer] = self.kmers[kmer]
            n += 1
            if n % 10000 == 0:
                system_print_normal('Processed', n, 'out of', len(self.kmers), 'kmers.\r')
        system_print_normal('Merged reference counts for', len(self.kmers), 'kmers.')
        with open('counts.txt', 'w') as txt_file:
            for kmer in self.kmers:
                txt_file.write(kmer + ':' + str(self.kmers[kmer]['count']) + '\n')
        n = 0
        #for track in self.tracks:
        #    with open(os.path.join(self.get_current_job_directory(), track + '.json'), 'w') as json_file:
        #        json.dump(self.tracks[track], json_file, indent = 4, sort_keys = True)
        #    n += 1
        #    if n % 1000 == 0:
        #        system_print('Exported', n, 'out of', len(self.tracks), 'tracks.\r')
        #with open(os.path.join(self.get_current_job_directory(), 'batch_merge.json'), 'w') as json_file:
        #    json.dump({track: track + '.json' for track in self.tracks}, json_file, indent = 4)
        system_print_high('Exported junction kmers for', len(self.tracks), 'tracks.')
        return self.tracks

# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #

class FilterJunctionKmersJob(reduction.FilterInnerKmersJob):

    # ============================================================================================================================ #
    # Launcher
    # ============================================================================================================================ #

    _name = 'FilterJunctionKmersJob'
    _category = 'preprocessing'
    _previous_job = ScoreJunctionKmersJob 

    @staticmethod
    def launch(**kwargs):
        job = FilterJunctionKmersJob(**kwargs)
        job.execute()

    # ============================================================================================================================ #
    # MapReduce overrides
    # ============================================================================================================================ #

    def execute(self):
        c = config.Configuration()
        system_print_high('================== Stage ' + self._name + 'started..')
        start = time.clock() 
        self.create_output_directories()
        self.kmers = {}
        for track in self.tracks:
            self.transform(self.tracks[track], track)
        self.filter_loci()
        self.export_kmers()
        end = time.clock()
        system_print_high('################## Stage ' + self._name + ' finished. Execution time', end - start)

    #def load_inputs(self):
    #    c = config.Configuration()
    #    self.kmers = {}
    #    self.tracks = self.load_previous_job_results()
    #    self.round_robin(self.tracks)

    # only breakpoint loci may lack a mask, if has more than one loci in such cases check for overlap. If overlap found ignore kmer. If not found then ok.
    def transform(self, track, track_name):
        if track_name:
        #with open(os.path.join(self.get_previous_job_directory(), track), 'r') as json_file:
            #kmers = json.load(json_file)
            kmers = track
            for kmer in kmers:
                if kmer.find('N') != -1:
                    continue
                if kmers[kmer]['count'] <= 3:
                    if not kmer in self.kmers:
                        interest_kmers = {}
                        self.kmers[kmer] = {}
                        self.kmers[kmer]['loci'] = copy.deepcopy(kmers[kmer]['loci'])
                        self.kmers[kmer]['total'] = 0
                        self.kmers[kmer]['count'] = 0
                        self.kmers[kmer]['doubt'] = 0
                        self.kmers[kmer]['source'] = kmers[kmer]['source']
                        self.kmers[kmer]['tracks'] = copy.deepcopy(kmers[kmer]['tracks'])
                        self.kmers[kmer]['reference'] = kmers[kmer]['count']
                        self.kmers[kmer]['interest_masks'] = {}
                        l = len(self.kmers[kmer]['loci'])
                        for locus in self.kmers[kmer]['loci']:
                            self.kmers[kmer]['loci'][locus]['masks'] = {self.kmers[kmer]['loci'][locus]['masks'][side]: True for side in self.kmers[kmer]['loci'][locus]['masks']}
                        for locus in self.kmers[kmer]['loci']:
                            if 'junction_' in locus: #or len(self.kmers[kmer]['loci'][locus]['masks']) != 2:
                                self.kmers[kmer]['interest_masks'].update(self.kmers[kmer]['loci'][locus]['masks'])
            return None

    def is_kmer_returning(self, kmer):
        c = config.Configuration()
        for track in kmer['tracks']:
            t = c.tracks[track]
            for locus in kmer['loci']:
                if not 'junction' in locus:
                    start = int(locus.split('_')[1])
                    if abs(start - t.end) < 2 * c.ksize:
                        return True
                    if abs(start - t.begin) < 2 * c.ksize:
                        return True
        return False

    def filter_loci(self):
        remove = {}
        for kmer in self.kmers:
            l_1 = len(self.kmers[kmer]['loci'])
            self.kmers[kmer]['filtered_loci'] = {}
            loci = copy.deepcopy(self.kmers[kmer]['loci'])
            for locus in list(self.kmers[kmer]['loci'].keys()):
                l = self.get_shared_masks(self.kmers[kmer]['interest_masks'], self.kmers[kmer]['loci'][locus]['masks'])
                if l == 0:
                    self.kmers[kmer]['filtered_loci'][locus] = self.kmers[kmer]['loci'][locus]
                    self.kmers[kmer]['loci'].pop(locus, None)
            l_2 = len(self.kmers[kmer]['loci'])
            # filter non-overlapping loci
            a = any(map(lambda locus: len(self.kmers[kmer]['loci'][locus]['masks']) != 2, self.kmers[kmer]['loci']))
            b = all(map(lambda locus: 'junction' in locus, self.kmers[kmer]['loci']))
            if a: # there are junction loci with missing masks
                if l_1 != l_2: # non-junction loci exist and some were filtered
                    if b: # all non-junction loci were filtered, count them instead 
                        self.kmers[kmer]['junction_loci'] = self.kmers[kmer]['loci']
                        self.kmers[kmer]['loci'] = {locus: loci[locus] for locus in loci if not 'junction' in locus}
                        self.kmers[kmer]['inverse'] = True
                    else: # some non-junction loci remain
                        remove[kmer] = True
                else: # all known loci are being counted (or non-junction loci don't exist), masks shouldn't make a difference
                    for locus in self.kmers[kmer]['loci']:
                        self.kmers[kmer]['loci'][locus]['masks'] = {}
            self.kmers[kmer].pop('interest_masks', None)
        for kmer in remove:
            self.kmers.pop(kmer, None)

    def output_batch(self, batch):
        self.filter_loci()
        json_file = open(os.path.join(self.get_current_job_directory(), 'batch_' + str(self.index) + '.json'), 'w')
        json.dump(self.kmers, json_file, sort_keys = True, indent = 4)
        json_file.close()

    def reduce(self):
        self.kmers = {}
        for batch in self.load_output():
            for kmer in batch:
                self.kmers[kmer] = batch[kmer]
        self.export_kmers()

    def export_kmers(self):
        system_print_high('Extracted', len(self.kmers), 'kmers.')
        returning_kmers = {kmer: self.kmers[kmer] for kmer in self.kmers if self.is_kmer_returning(self.kmers[kmer])}
        with open(os.path.join(self.get_current_job_directory(), 'returning.json'), 'w') as json_file:
            json.dump(returning_kmers, json_file, indent = 4)
        self.kmers = {kmer: self.kmers[kmer] for kmer in self.kmers if not self.is_kmer_returning(self.kmers[kmer])}
        system_print_high(len(self.kmers), 'kmers remaining after filtering returning kmers.')
        with open(os.path.join(self.get_current_job_directory(), 'kmers.json'), 'w') as json_file:
            json.dump(self.kmers, json_file, indent = 4, sort_keys = True)
        self.tracks = {}
        for kmer in self.kmers:
            for track in self.kmers[kmer]['tracks']:
                if not track in self.tracks:
                    self.tracks[track] = {}
                self.tracks[track][kmer] = self.kmers[kmer]
        system_print_high('Exported', len(self.tracks), 'tracks with eligible junction kmers.')
        for track in self.tracks:
            with open(os.path.join(self.get_current_job_directory(), track + '.json'), 'w') as json_file:
                json.dump(self.tracks[track], json_file, indent = 4)
