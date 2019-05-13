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
    depth,
    config,
    counter,
    simulator,
    counttable,
    map_reduce,
    statistics,
    visualizer,
    programming,
)

import numpy

from nebula.debug import *
from nebula.kmers import *
from nebula.commons import *
from nebula.chromosomes import *
print = pretty_print

# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #

class ExtractInnerKmersJob(map_reduce.Job):

    _name = 'ExtractInnerKmersJob'
    _category = 'preprocessing'
    _previous_job = None

    # ============================================================================================================================ #
    # Launcher
    # ============================================================================================================================ #

    @staticmethod
    def launch(**kwargs):
        job = ExtractInnerKmersJob(**kwargs)
        job.execute()

    # ============================================================================================================================ #
    # MapReduce overrides
    # ============================================================================================================================ #

    def load_inputs(self):
        c = config.Configuration()
        extract_whole_genome()
        self.tracks = c.tracks
        self.load_reference_counts_provider()
        self.round_robin(self.tracks, filter_func = lambda track: track.end - track.begin > 1000000)

    def transform(self, track, track_name):
        print(cyan(track_name))
        c = config.Configuration()
        inner_kmers = self.extract_inner_kmers(track)
        if len(inner_kmers) == 0:
            print(red('skipping', track_name, 'no inner kmers found'))
            return None
        name = track_name  + '.json'
        with open(os.path.join(self.get_current_job_directory(), name), 'w') as json_file:
            json.dump(inner_kmers, json_file, sort_keys = True, indent = 4)
        return name

    def extract_inner_kmers(self, track):
        c = config.Configuration()
        chrom = extract_chromosome(track.chrom.lower())
        if not chrom:
            print(red(track.chrom.lower()))
            return None
        inner_kmers = {}
        if track.svtype == 'INS':
            inner_seq = track.seq
            prefix = chrom[track.begin - c.ksize: track.begin]
            suffix = chrom[track.end: track.end + c.ksize]
            inner_seq = prefix + inner_seq + suffix
            for i in range(c.ksize, c.ksize + len(track.seq) - c.ksize + 1):
                kmer = canonicalize(inner_seq[i: i + c.ksize])
                if not kmer in inner_kmers:
                    inner_kmers[kmer] = {
                        'reference': self.reference_counts_provider.get_kmer_count(kmer),
                        'loci': {},
                    }
                inner_kmers[kmer]['loci']['inside_' + track.id] = {
                    'seq': {
                        'all': inner_seq[i - c.ksize: i + c.ksize + c.ksize],
                        'left': inner_seq[i - c.ksize: i],
                        'right': inner_seq[i + c.ksize: i + c.ksize + c.ksize]
                    }
                }
        if track.svtype == 'DEL':
            inner_seq = chrom[track.begin: track.end]
            for i in range(len(inner_seq) - c.ksize + 1):
                kmer = canonicalize(inner_seq[i: i + c.ksize])
                if not kmer in inner_kmers:
                    inner_kmers[kmer] = {
                        'reference': self.reference_counts_provider.get_kmer_count(kmer),
                        'loci': {},
                    }
        if len(inner_kmers) <= 1000:
            return inner_kmers
        else:
            items = sorted(inner_kmers.items(), key = lambda item: item[1]['reference'])[0 : 1000]
            return {item[0]: item[1] for item in items}


# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #

class ExtractLociIndicatorKmersJob(map_reduce.Job):

    # ============================================================================================================================ #
    # Launcher
    # ============================================================================================================================ #

    _name = 'ExtractLociIndicatorKmersJob'
    _category = 'preprocessing'
    _previous_job = ExtractInnerKmersJob

    @staticmethod
    def launch(**kwargs):
        job = ExtractLociIndicatorKmersJob(**kwargs)
        job.execute()

    # ============================================================================================================================ #
    # MapReduce overrides
    # ============================================================================================================================ #

    def load_inputs(self):
        c = config.Configuration()
        self.chroms = extract_whole_genome()
        self.tracks = self.load_previous_job_results()
        self.inner_kmers = {}
        for track in self.tracks:
            print(track)
            with open(os.path.join(self.get_previous_job_directory(), self.tracks[track]), 'r') as json_file:
                kmers = json.load(json_file)
                for kmer in kmers:
                    if not kmer in self.inner_kmers:
                        self.inner_kmers[kmer] = kmers[kmer]
                    self.inner_kmers[kmer]['tracks'][track] = kmers[kmer_type][kmer]['track']
        print('Finding loci for', green(len(self.inner_kmers)), 'kmers')
        self.round_robin(self.chroms)

    def transform(self, sequence, chrom):
        c = config.Configuration()
        index = 0
        slack = c.ksize
        print(cyan(chrom, len(sequence)))
        t = time.time()
        for kmer in stream_kmers(c.ksize, True, True, sequence):
            if kmer in self.inner_kmers:
                locus = chrom + '_' + str(index)
                self.inner_kmers[kmer]['loci'][locus] = {
                    'seq': {
                        'all': sequence[index - slack: index + c.ksize + slack],
                        'left': sequence[index - slack: index],
                        'right': sequence[index + c.ksize: index + c.ksize + slack]
                    }
                }
            index += 1
            if index % 10000 == 0:
                s = time.time()
                p = (len(sequence) - index) / float(len(sequence))
                e = (1.0 - p) * (((1.0 / p) * (s - t)) / 3600)
                print('{:5}'.format(chrom), 'progress:', '{:12.10f}'.format(p), 'took:', '{:14.10f}'.format(s - t), 'ETA:', '{:12.10f}'.format(e))
        return None

    def output_batch(self, batch):
        json_file = open(os.path.join(self.get_current_job_directory(), 'batch_' + str(self.index) + '.json'), 'w')
        json.dump(self.inner_kmers, json_file, sort_keys = True, indent = 4)
        json_file.close()
        exit()

    def reduce(self):
        for i in range(0, self.num_threads):
            print('adding batch', i)
            path = os.path.join(self.get_current_job_directory(), 'batch_' + str(i) + '.json') 
            if not os.path.isfile(path):
                print(red('couldn\'t find batch'), i, red('results will be unreliable'))
                continue
            with open (path, 'r') as json_file:
                batch = json.load(json_file)
                for kmer in batch:
                    self.inner_kmers[kmer]['loci'].update(batch[kmer]['loci'])
        for track in self.tracks:
            self.tracks[track] = {}
        for kmer in self.inner_kmers:
            for track in self.inner_kmers[kmer]['tracks']:
                self.tracks[track][kmer] = self.inner_kmers[kmer]
        for track in self.tracks:
            with open(os.path.join(self.get_current_job_directory(), 'indicator_kmers_' + track + '.json'), 'w') as track_file:
                json.dump(self.tracks[track], track_file, indent = 4, sort_keys = True)
        with open(os.path.join(self.get_current_job_directory(), 'batch_merge.json'), 'w') as json_file:
            json.dump({track: 'indicator_kmers_' + track + '.json' for track in self.tracks}, json_file, indent = 4)

    def plot_kmer_reference_count(self):
        x = []
        for track in self.tracks:
            print(track)
            with open(os.path.join(self.get_current_job_directory(), self.tracks[track]), 'r') as json_file:
                kmers = json.load(json_file)['inner_kmers']
                for kmer in kmers:
                    x.append(kmers[kmer]['reference'])
        visualizer.histogram(x = x, name = 'reference_count', path = self.get_current_job_directory(), x_label = 'kmer count in reference', y_label = 'number of kmers', step = 0.1)

# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #

class FilterLociIndicatorKmersJob(map_reduce.Job):

    # ============================================================================================================================ #
    # Launcher
    # ============================================================================================================================ #

    _name = 'FilterLociIndicatorKmersJob'
    _category = 'preprocessing'
    _previous_job = ExtractLociIndicatorKmersJob

    @staticmethod
    def launch(**kwargs):
        job = FilterLociIndicatorKmersJob(**kwargs)
        job.execute()

    # ============================================================================================================================ #
    # MapReduce overrides
    # ============================================================================================================================ #

    def load_inputs(self):
        c = config.Configuration()
        self.kmers = {}
        self.tracks = self.load_previous_job_results()
        self.round_robin(self.tracks)

    def transform(self, track, track_name):
        c = config.Configuration()
        with open(os.path.join(self.get_previous_job_directory(), track), 'r') as json_file:
            kmers = json.load(json_file)
            t = c.tracks[track_name]
            for kmer in kmers:
                if kmer.find('N') != -1:
                    continue
                seed = sum(list(map(lambda s: ord(s), kmer)))
                if not kmer in self.kmers:
                    self.kmers[kmer] = {}
                    self.kmers[kmer]['loci'] = kmers[kmer]['loci']
                    self.kmers[kmer]['total'] = 0
                    self.kmers[kmer]['count'] = 0
                    self.kmers[kmer]['doubt'] = 0
                    self.kmers[kmer]['tracks'] = kmers[kmer]['tracks']
                    self.kmers[kmer]['reference'] = kmers[kmer]['reference']
                    self.kmers[kmer]['interest_masks'] = {}
                    for locus in self.kmers[kmer]['loci']:
                        self.kmers[kmer]['loci'][locus]['masks'] = {self.kmers[kmer]['loci'][locus]['seq']['left']: True, self.kmers[kmer]['loci'][locus]['seq']['right']: True}
                for locus in self.kmers[kmer]['loci']:
                    tokens = locus.split('_')
                    if tokens[0].lower() == t.chrom.lower() and int(tokens[1]) >= t.begin and int(tokens[1]) < t.end:
                        self.kmers[kmer]['interest_masks'].update(self.kmers[kmer]['loci'][locus]['masks'])
        return None

    def output_batch(self, batch):
        for kmer in self.kmers:
            for locus in self.kmers[kmer]['loci'].keys():
                l = self.get_shared_masks(self.kmers[kmer]['interest_masks'], self.kmers[kmer]['loci'][locus]['masks'])
                if l == 0:
                    self.kmers[kmer]['loci'].pop(locus, None)
            self.kmers[kmer].pop('interest_masks', None)
            self.kmers[kmer]['reduction'] = self.kmers[kmer]['reference']
            self.kmers[kmer]['reference'] = len(self.kmers[kmer]['loci'])
        json_file = open(os.path.join(self.get_current_job_directory(), 'batch_' + str(self.index) + '.json'), 'w')
        json.dump(self.kmers, json_file, sort_keys = True, indent = 4)
        json_file.close()
        exit()

    def get_shared_masks(self, interest_kmers, kmers):
        l = []
        for x in kmers:
            for y in interest_kmers:
                if is_canonical_subsequence(x[4:-4], y):
                    l.append(x)
                    break
        return len(l)

    def reduce(self):
        self.kmers = {}
        for batch in self.load_output():
            for kmer in batch:
                self.kmers[kmer] = batch[kmer]
        #
        with open(os.path.join(self.get_current_job_directory(), 'kmers.json'), 'w') as json_file:
            json.dump(self.kmers, json_file, indent = 4, sort_keys = True)
        self.tracks = {}
        for kmer in self.kmers:
            for track in self.kmers[kmer]['tracks']:
                if not track in self.tracks:
                    self.tracks[track] = {}
                self.tracks[track][kmer] = self.kmers[kmer]
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

class CountLociIndicatorKmersJob(map_reduce.FirstGenotypingJob, counter.BaseExactCountingJob):

    # ============================================================================================================================ #
    # Launcher
    # ============================================================================================================================ #

    _name = 'CountLociIndicatorKmersJob'
    _category = 'preprocessing'
    _previous_job = FilterLociIndicatorKmersJob
    _counter_mode = 0

    @staticmethod
    def launch(**kwargs):
        job = CountLociIndicatorKmersJob(**kwargs)
        job.execute()

    # ============================================================================================================================ #
    # MapReduce overrides
    # ============================================================================================================================ #

    def load_inputs(self):
        c = config.Configuration()
        self.kmers = {}
        self.depth_mers = {}
        with open(os.path.join(self.get_previous_job_directory(), 'kmers.json'), 'r') as json_file:
            self.kmers = json.load(json_file)
        print(len(self.kmers), 'inner kmers')
        #self.get_depth_of_coverage_kmers()
        with open(os.path.join(self.get_current_job_directory(), 'pre_inner_kmers.json'), 'w') as json_file:
            _kmers = {}
            for kmer in self.kmers:
                _kmers[kmer] = {}
                _kmers[kmer]['loci'] = {}
                for locus in self.kmers[kmer]['loci']:
                    _kmers[kmer]['loci'][locus] = {}
                    _kmers[kmer]['loci'][locus]['masks'] = self.kmers[kmer]['loci'][locus]['masks']
            for kmer in self.depth_mers:
                _kmers[kmer] = {}
                _kmers[kmer]['loci'] = {}
            json.dump(_kmers, json_file, indent = 4)
        self.round_robin()

    def get_depth_of_coverage_kmers(self):
        n = 100000
        self.depth_mers = {}
        self.load_reference_counts_provider() 
        for kmer, count in self.reference_counts_provider.stream_kmers():
            if count == 1 and kmer.find('N') == -1:
                canon = canonicalize(kmer)
                if not kmer in self.kmers and not reverse_complement(kmer) in self.kmers:
                    self.depth_mers[canon] = {'loci': {}}
                    n -= 1
                    if n == 0:
                        break
        print('Counting', green(len(self.depth_mers)), 'unique kmers')
        self.unload_reference_counts_provider()

    def merge_count(self, kmer, tokens):
        count = tokens[0] 
        total = tokens[1] 
        canon = canonicalize(kmer)
        self.kmers[canon]['count'] += count / 2
        self.kmers[canon]['total'] += total / 2

    def reduce(self):
        c = config.Configuration()
        self.merge_counts()
        #self.estimate_depth_of_coverage()
        with open(os.path.join(self.get_current_job_directory(), 'kmers.json'), 'w') as json_file:
            json.dump(self.kmers, json_file, indent = 4, sort_keys = True)
        self.tracks = {}
        for kmer in self.kmers:
            for track in self.kmers[kmer]['tracks']:
                if not track in self.tracks:
                    self.tracks[track] = {}
                self.tracks[track][kmer] = self.kmers[kmer]
        for track in self.tracks:
            print('exporting track', track)
            with open(os.path.join(self.get_current_job_directory(), 'indicator_kmers_' + track + '.json'), 'w') as json_file:
                json.dump(self.tracks[track], json_file, indent = 4, sort_keys = True)
        with open(os.path.join(self.get_current_job_directory(), 'batch_merge.json'), 'w') as json_file:
            json.dump({track: 'indicator_kmers_' + track + '.json' for track in self.tracks}, json_file, indent = 4)

    def estimate_depth_of_coverage(self):
        self.counts = list(map(lambda kmer: self.kmers[kmer]['count'], self.depth_mers))
        self.mean = numpy.mean(self.counts)
        self.std = numpy.std(self.counts)
        print(len(self.counts))
        print('mean:', self.mean)
        print('std:', self.std)
        # filter outliers
        self.counts = list(filter(lambda x: x < 3 * self.mean, self.counts))
        self.mean = numpy.mean(self.counts)
        self.std = numpy.std(self.counts)
        print(len(self.counts))
        print('mean:', self.mean)
        print('std:', self.std)
        # filter outliers
        self.counts = list(filter(lambda x: x < 2 * self.mean, self.counts))
        self.mean = numpy.mean(self.counts)
        self.std = numpy.std(self.counts)
        print(len(self.counts))
        print('mean:', self.mean)
        print('std:', self.std)
        #
        self.plot_reference_distribution([ self.counts[i] for i in sorted(random.sample(xrange(len(self.counts)), 10000)) ])
        with open(os.path.join(self.get_current_job_directory(), 'stats_' + str(c.ksize) + '.json'), 'w') as json_file:
            json.dump({ 'mean': self.mean, 'std': self.std }, json_file, sort_keys = True, indent = 4)

# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #

class AdjustCoverageGcContentJob(map_reduce.BaseGenotypingJob):

    # ============================================================================================================================ #
    # Launcher
    # ============================================================================================================================ #

    _name = 'AdjustCoverageGcContentJob'
    _category = 'preprocessing'
    _previous_job = CountLociIndicatorKmersJob

    @staticmethod
    def launch(**kwargs):
        job = AdjustCoverageGcContentJob(**kwargs)
        job.execute()

    # ============================================================================================================================ #
    # MapReduce overrides
    # ============================================================================================================================ #

    def load_inputs(self):
        c = config.Configuration()
        with open(os.path.join(self.get_previous_job_directory(), 'kmers.json'), 'r') as json_file:
            self.kmers = json.load(json_file)
        print(len(self.kmers))
        gc_coverage_job = depth.ChromosomeGcContentEstimationJob()
        with open(os.path.join(gc_coverage_job.get_current_job_directory(), 'coverage.json'), 'r') as json_file:
            self.coverage = json.load(json_file)
        print('Adjusting GC coverage for', green(len(self.kmers)), 'kmers')
        n = 0
        for kmer in self.kmers:
            self.transform(self.kmers[kmer], kmer)
            n += 1
            if n % 1000 == 0:
                print(n, 'out of', len(self.kmers))
        self.tracks = {}
        for kmer in self.kmers:
            for track in self.kmers[kmer]['tracks']:
                if not track in self.tracks:
                    self.tracks[track] = {}
                self.tracks[track][kmer] = self.kmers[kmer]
        for track in self.tracks:
            print('exporting track', track)
            with open(os.path.join(self.get_current_job_directory(), 'indicator_kmers_' + track + '.json'), 'w') as json_file:
                json.dump(self.tracks[track], json_file, indent = 4, sort_keys = True)
        with open(os.path.join(self.get_current_job_directory(), 'batch_merge.json'), 'w') as json_file:
            json.dump({track: 'indicator_kmers_' + track + '.json' for track in self.tracks}, json_file, indent = 4)
        exit()

    def transform(self, kmer, k):
        coverage = []
        for locus in kmer['loci']:
            gc = calculate_gc_content(kmer['loci'][locus]['seq']['all'])
            kmer['loci'][locus]['coverage'] = self.coverage[gc]
            coverage.append(self.coverage[gc])
        kmer['coverage'] = statistics.mean(coverage)

# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #
# ============================================================================================================================ #

class LociIndicatorKmersIntegerProgrammingJob(programming.IntegerProgrammingJob):

    _name = 'LociIndicatorKmersIntegerProgrammingJob'
    _category = 'preprocessing'
    _previous_job = AdjustCoverageGcContentJob
    _kmer_type = 'inner'

    @staticmethod
    def launch(**kwargs):
        c = config.Configuration()
        job = LociIndicatorKmersIntegerProgrammingJob(**kwargs)
        job.execute()

    # ============================================================================================================================ #
    # MapReduce overrides
    # ============================================================================================================================ #

    def transform(self, track, track_name):
        c = config.Configuration()
        print(green(track_name))
        t = c.tracks[track_name] 
        with open(os.path.join(self.get_previous_job_directory(), track), 'r') as json_file:
            kmers = json.load(json_file)
            if len(kmers) == 0:
                print('no inner kmers found for', red(track_name))
                return None
            _kmers = {kmer: kmers[kmer] for kmer in list(filter(lambda kmer: len(kmers[kmer]['tracks']) == 1, kmers))}
            unique_kmers = list(filter(lambda kmer: len(_kmers[kmer]['loci']) == 1, _kmers))
            non_unique_kmers = list(filter(lambda kmer: len(_kmers[kmer]['loci']) != 1, _kmers))
            # let's limit the number of kmers to 50 to help with integer programming runtime
            #if len(unique_kmers) == 0:
            #    return None
            if len(unique_kmers) >= 5:
                kmers = {kmer: _kmers[kmer] for kmer in unique_kmers[:min(50, len(unique_kmers))]}
            else:
                kmers = {kmer: _kmers[kmer] for kmer in unique_kmers}
                for kmer in non_unique_kmers:
                    kmers[kmer] = _kmers[kmer]
                    if len(kmers) > 50:
                        break
            for kmer in kmers:
                self.lp_kmers[kmer] = {}
                self.lp_kmers[kmer]['type'] = self._kmer_type
                self.lp_kmers[kmer]['count'] = kmers[kmer]['count']
                self.lp_kmers[kmer]['doubt'] = kmers[kmer]['doubt']
                self.lp_kmers[kmer]['total'] = kmers[kmer]['total']
                self.lp_kmers[kmer]['weight'] = 1.0
                self.lp_kmers[kmer]['coverage'] = kmers[kmer]['coverage']
                self.lp_kmers[kmer]['reference'] = len(kmers[kmer]['loci'])
                self.lp_kmers[kmer]['reduction'] = kmers[kmer]['reference']
                self.lp_kmers[kmer]['tracks'] = kmers[kmer]['tracks']
                self.lp_kmers[kmer]['loci'] = list(map(lambda l: l, kmers[kmer]['loci']))
        path = os.path.join(self.get_current_job_directory(), 'indicator_kmers_' + track_name + '.json')
        with open(path, 'w') as json_file:
            json.dump({kmer: self.lp_kmers[kmer] for kmer in kmers}, json_file, indent = 4, sort_keys = True)
        return path

# ============================================================================================================================ #
# Main
# ============================================================================================================================ #

if __name__ == '__main__':
    config.init()
    c = config.Configuration()
    getattr(sys.modules[__name__], c.job).launch(resume_from_reduce = c.reduce)
