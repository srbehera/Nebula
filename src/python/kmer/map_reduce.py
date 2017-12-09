import io
import os
import re
import pwd
import sys
import copy
import json
import time
import argparse
import traceback

from kmer import (
    config,
    commons,
)

import colorama

# ============================================================================================================================ #
# Job class, describes a MapReducer job
# Will apply a transformation to a library of structural variation:
# 1. Divides the library into a number of `batches`
# 2. Each batch includes one or more `tracks` (each track is a structural variation)
# 3. Applies the function `transfer` to each track and outputs the result
# 4. Merges the transformed tracks into a whole
# ============================================================================================================================ #

class Job(object):

    def __init__(self, job_name, previous_job_name, **kwargs):
        self.job_name = job_name
        self.previous_job_name = previous_job_name
        self.index = -1
        self.batch = {}
        self.children = {}
        self.run_for_certain_batches_only = False

    def prepare(self):
        pass

    def execute(self, **kwargs):
        c = config.Configuration()
        if 'batches_to_run' in kwargs:
            self.run_for_certain_batches_only = True
            self.batches_to_run = kwargs['batches_to_run']
        self.prepare()
        self.create_output_directories()
        self.find_thread_count()
        self.load_inputs()
        self.distribute_workload()
        self.wait_for_children()
        self.reduce()
        # self.clean_up()

    # this for when you need to make small adjustments to the output after the job has finished but don't want to run it all over again
    def post_process(self):
        pass

    def find_thread_count(self):
        c = config.Configuration()
        max_index = 0
        for index in range(0, c.max_threads):
            path = os.path.join(self.get_previous_job_directory(), 'batch_' + str(index) + '.json')
            if os.path.isfile(path):
                max_index = index + 1
        self.num_threads = max_index

    def load_inputs(self):
        for index in range(0, self.num_threads):
            path = os.path.join(self.get_previous_job_directory(), 'batch_' + str(index) + '.json')
            with open(path, 'r') as json_file:
                self.batch[index] = json.load(json_file)

    def distribute_workload(self):
        for index in range(0, self.num_threads):
            if self.run_for_certain_batches_only:
                if not index in self.batches_to_run:
                    continue
            pid = os.fork()
            if pid == 0:
                # forked process
                self.index = index
                self.run_batch(self.batch[index])
            else:
                # main process
                self.children[pid] = True
                print('spawned child ', pid)

    def run_batch(self, batch):
        c = config.Configuration()
        for track in batch:
            batch[track] = self.transform(batch[track], track)
        self.output_batch(batch)
        print(colorama.Fore.GREEN + 'process ', self.index, ' done')

    def transform(track, track_name, index):
        return track

    def output_batch(self, batch):
        # output manually, io redirection could get entangled with multiple client/servers
        with open(os.path.join(self.get_current_job_directory(), 'batch_' + str(self.index) + '.json'), 'w') as json_file:
            json.dump(batch, json_file, sort_keys = True, indent = 4, separators = (',', ': '))
        exit()

    def wait_for_children(self):
        while True:
            (pid, e) = os.wait()
            self.children.pop(pid, None)
            print(colorama.Fore.RED + 'pid ', pid, 'finished')
            if len(self.children) == 0:
                break
        print('all forks done, merging output ...')

    def merge(self, outputs):
        pass

    def plot(self, outputs):
        pass

    def sort(self, outputs):
        pass

    def reduce(self):
        c = config.Configuration()
        output = {}
        for i in range(0, self.num_threads):
            path = os.path.join(self.get_current_job_directory(), 'batch_' + str(i) + '.json')
            if os.path.isfile(path):
                with open(path, 'r') as json_file:
                    batch = json.load(json_file)
                    output.update(batch)
        with open(os.path.join(self.get_current_job_directory(), 'merge.json'), 'w') as json_file:
            json.dump(output, json_file, sort_keys = True, indent = 4, separators = (',', ': '))
        self.merge(output)
        self.plot(output)

    def clean_up(self):
        c = config.Configuration()
        for i in range(0, self.num_threads):
            path = os.path.join(self.get_current_job_directory(), 'batch_' + str(i) + '.json')
            os.remove(path)

    # ============================================================================================================================ #
    # filesystem helpers
    # ============================================================================================================================ #

    def get_output_directory(self):
        c = config.Configuration()
        bed_file_name = c.bed_file.split('/')[-1]
        return os.path.abspath(os.path.join(os.path.dirname(__file__),\
            '../../../output/' + bed_file_name + '/' + str(c.ksize) + '/'))

    def get_previous_job_directory(self):
        # get rid of the final _
        return os.path.abspath(os.path.join(self.get_output_directory(), self.previous_job_name[:-1]))

    def get_current_job_directory(self):
        # get rid of the final _
        return os.path.abspath(os.path.join(self.get_output_directory(), self.job_name[:-1]))

    def create_output_directories(self):
        dir = self.get_output_directory()
        if not os.path.exists(dir):
            os.makedirs(dir)
        dir = self.get_current_job_directory()
        if not os.path.exists(dir):
            os.makedirs(dir)
