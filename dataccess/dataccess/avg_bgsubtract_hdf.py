# Author: O. Hoidn

import pandas as pd
import re
import pdb
import sys
import math
import numpy as np
import Image
import glob
import argparse
import os
import ipdb
import dill
import sys


import config
if not config.smd:
    from dataccess import psana_get
else:
    from psana import *
from dataccess import toscript
from functools import partial
import config # config.py in local directory

from mpi4py import MPI
comm = MPI.COMM_WORLD

# validate contents of config.py
if not config.exppath:
    raise ValueError("config.exppath: must be string of length > 0")
try:
    expname = config.exppath.split('/')[1]
except:
    raise ValueError("config.exppath: incorrect format")

# TODO: ditto... validate values of other parameters in config.py
# do this here or in the top-level script?

# Replace the event-code driven method of detecting blank frames with
# something more reliable (i.e. with fewer edge cases)

from dataccess import utils
from pathos.multiprocessing import ProcessingPool

#XTC_DIR = '/reg/d/psdm/MEC/' + expname + '/xtc/'
XTC_DIR = '/reg/d/psdm/' + config.exppath + '/xtc/'

## TODO: memoize timestamp lookup
#def get_run_clusters(interval = None, exppath = config.exppath, max_interval = 50.):
#    """
#    Returns a list of lists containing clusters of run numbers whose xtc data 
#    files were created within max_interval seconds of each other. Testing with
#    LD67 data showed 50 seconds to be a good max_interval.
#
#    interval is a tuple of the form [run_low, run_high) indicating a  range of 
#    run numbers to limit this operation to
#    """
#    XTC_NAME = "/reg/d/psdm/" + exppath +  r"/xtc/e441-r%04d-s01-c00.xtc"
#    key = lambda run_num: os.path.getmtime(XTC_NAME%run_num)
#    def cluster(data, maxgap, key = lambda x: x):
#        '''Arrange data into groups where successive elements
#           differ by no more than *maxgap*
#
#           selector is a function that extracts values for comparison from the
#           elements of data
#
#            >>> cluster([1, 6, 9, 100, 102, 105, 109, 134, 139], maxgap=10)
#            [[1, 6, 9], [100, 102, 105, 109], [134, 139]]
#
#            >>> cluster([1, 6, 9, 99, 100, 102, 105, 134, 139, 141], maxgap=10)
#            [[1, 6, 9], [99, 100, 102, 105], [134, 139, 141]]
#
#        '''
#        data.sort(key = key)
#        groups = [[data[0]]]
#        for x in data[1:]:
#            if abs(key(x) - key(groups[-1][-1])) <= maxgap:
#                groups[-1].append(x)
#            else:
#                groups.append([x])
#        return groups
#
#    all_runs = get_all_runs(exppath = exppath)
#    if interval:
#        runs = range(*interval)
#        if not set(runs).issubset(set(all_runs)):
#            raise ValueError("invalid range of run numbers given")
#    else:
#        runs = all_runs
#    return cluster(runs, max_interval, key = key)



@utils.eager_persist_to_file("cache/get_signal_bg_one_run/")
def get_signal_bg_one_run(runNum, detid = 1, sigma_max = 1000.0,
event_data_getter = None, event_mask = None, **kwargs):
    # TODO: remove sigma_max discrimination
    def filter_events(eventlist, blanks):
        """
        Return the indices of outliers (not including blank frames) in the list of 
        data arrays, along with a list of 'good' (neither outlier nor blank) indices.

        """
        def event_valid(nevent):
            if event_mask:
                run_mask = event_mask[runNum]
                return run_mask[nevent]
            else:
                return True
        totalcounts = np.array(map(np.sum, eventlist))
        nonblank_counts_enumerated = filter(lambda (indx, counts): indx not in blanks, enumerate(totalcounts))
        nonblank_counts = map(lambda x: x[1], nonblank_counts_enumerated)
        median = np.median(nonblank_counts)
        std = np.std(nonblank_counts)
        print  'signal levels:', totalcounts
        print median, std
        # indices of the events in ascending order of total signal
        outlier_indices =\
            [i
            for i, counts in nonblank_counts_enumerated
            if (np.abs(counts - median) > std * sigma_max) or not event_valid(i)]
        good_indices =\
            [i
            for i in range(len(eventlist))
            if ((i not in outlier_indices) and (i not in blanks))]
        return outlier_indices, good_indices

    def spacing_between(arr):
        """
        Given an array (intended to be an array of indices of blank runs), return the
        interval between successive values (assumed to be constant).

        The array must be of length >= 1

        60 Hz datasets should have an interval of 12 between blank indices, 
        whereas 120Hz datasets should have an interval of 24

        To be called ONLY if config.smd == False
        """
        diffs = np.diff(arr)[1:]
        return int(np.sum(diffs))/len(diffs)

    def get_bg(eventlist, vetted_blanks):
        if vetted_blanks:
            return reduce(lambda x, y: x + y, eventlist[vetted_blanks])/len(vetted_blanks)
        return np.zeros(np.shape(eventlist[0]))

    nfiles, eventlist, blanks = psana_get.getImg(detid, runNum)
    if spacing_between(blanks) == 24:
        vetted_blanks = blanks
    else:
        vetted_blanks = []
    outlier, good = filter_events(eventlist, vetted_blanks)
    bg = get_bg(eventlist, vetted_blanks)
    signal = reduce(lambda x, y: x + y, eventlist[good])/len(good)
    if event_data_getter is None:
        return signal, bg, []
    else:
        if event_mask is not None:
            event_data = map(event_data_getter, np.array(eventlist)[np.array(event_mask[runNum], dtype = bool)])
        else:
            event_data = map(event_data_getter, eventlist)
        return signal, bg, event_data

def get_image_quadrant(arr, i):
    """
    Takes a 2d array and returns the specified quadrant as a contiguous array
    if i = 0, 1, 2, or 3. Returns the array unaltered if i == -1.
    """
    dimy, dimx = np.shape(arr)
    split_x = [0, dimx/2, dimx]
    split_y = [0, dimy/2, dimy]
    result = []
    def piece(n, m):
        return  arr[split_y[n]: split_y[n + 1], split_x[m]: split_x[m + 1]]
    if i == -1:
        return arr
    else:
        return np.ascontiguousarray(piece(i / 2, i %2))

# TODO: more testing and refactor all of this!
@utils.eager_persist_to_file("cache/get_signal_bg_one_run_smd/")
def get_signal_bg_one_run_smd(runNum, detid, subregion_index = -1,
        event_data_getter = None, event_mask = None, **kwargs):
    def event_valid(nevent):
        if event_mask:
            run_mask = event_mask[runNum]
            return run_mask[nevent]
        else:
            return True
    DIVERTED_CODE = 162
    ds = DataSource('exp=%s:run=%d:smd' % (config.expname, runNum))
    det = Detector(config.detinfo_map[detid].device_name, ds.env())
    rank = comm.Get_rank()
    print "rank is", rank
    size = comm.Get_size()
    darkevents, event_data = [], []
    events_processed = 0
    def is_darkevent(evr):
        # temporary patch, valid for LK20 because end station A isn't running
#        for fifoEvent in evr.fifoEvents():
#            # In general, this will incorrectly add i = 0 to darkevents
#            if fifoEvent.eventCode() == DIVERTED_CODE:
#                return True
        return False
    for nevent, evt in enumerate(ds.events()):
        if (nevent % size == rank) and event_valid(nevent):
            evr = evt.get(EvrData.DataV4, Source('DetInfo(NoDetector.0:Evr.0)'))
            isdark = is_darkevent(evr)
            increment = det.image(evt)
            #increment = get_image_quadrant(det.image(evt), subregion_index)
            if increment is not None:
                if isdark:
                    darkevents.append(nevent)
                    try:
                        darksum += increment
                    except UnboundLocalError:
                        darksum = increment
                else:
                    try:
                        signalsum += increment
                    except UnboundLocalError:
                        signalsum = increment
                    if event_data_getter:
                        event_data.append(event_data_getter(get_image_quadrant(increment, subregion_index)))
                    events_processed += 1
        # TODO: for testing only. remove later.
#        if nevent >= rank:
#            break
    signalsum /= events_processed
    signalsum_final = np.empty_like(signalsum)
    comm.Allreduce(signalsum, signalsum_final)
    signalsum_final = get_image_quadrant(signalsum_final, subregion_index)
    darksum_final = np.empty_like(signalsum)
    try:
        darksum /= events_processed
        comm.Allreduce(darksum, darksum_final)
        darksum_final = get_image_quadrant(darksum_final, subregion_index)
    except UnboundLocalError:
        darksum_final = np.empty_like(signalsum_final)
    darkevents = comm.allgather(darkevents)
    events_processed = comm.allreduce(events_processed)
    if event_data_getter:
        event_data = comm.allgather(event_data)
    print "rank is: ", rank
    if rank == 0:
        print "processed ", events_processed, "events"
        print "dark events: ", darkevents
    if darkevents:
        darkevents = reduce(lambda x, y: x + y, darkevents)
    if event_data:
        event_data = reduce(lambda x, y: x + y, event_data)
    return signalsum_final, darksum_final, event_data


#@utils.eager_persist_to_file("cache/avg_bgsubtract_hdf/")
#def get_signal_bg_many(runList, detid, event_data_getter = None,
#    event_mask = None, **kwargs):
#    """
#    Return the averaged signal and background, and accumulated event data,
#    from running get_signal_bg_one_run over all runs specified.
#
#    Parameters
#    ----------
#    runList : list of ints
#    All others: see get_signal_bg_one_run
#
#    Returns
#    ----------
#    signal : 2-d np.ndarray
#        Averaged signal, subject to filtering by event_mask, and default
#        removal of outliers.
#    bg : 2-d np.ndarray
#        Averaged background.
#    event_mask : list of lists
#        Accumulated event data.
#    """
#    bg = np.zeros(config.detinfo_map[detid].dimensions)
#    signal = np.zeros(config.detinfo_map[detid].dimensions) 
#    event_data = []
#    for run_number in runList:
#        
#        output_one_run = get_signal_bg_one_run(run_number, detid,
#            event_data_getter = event_data_getter, event_mask = event_mask,
#            **kwargs)
#        signal_increment, bg_increment, event_data_entry = output_one_run
#        signal += (signal_increment / len(runList))
#        bg += (bg_increment / len(runList))
#        if event_data_getter is not None:
#            event_data.append(event_data_entry)
#    return signal, bg, event_data

@utils.eager_persist_to_file("cache/get_signal_bg_many_parallel/")
def get_signal_bg_many_parallel(runList, detid, event_data_getter = None,
    event_mask = None, **kwargs):
    """
    Parallel version of get_signal_bg_many
    """

    def mapfunc(run_number):
        return get_signal_bg_one_run(run_number, detid, event_data_getter =
            event_data_getter, event_mask = event_mask, **kwargs)
    def mapfunc_smd(run_number):
        return get_signal_bg_one_run_smd(run_number, detid, event_data_getter =
            event_data_getter, event_mask = event_mask, **kwargs)

    if config.smd:
        run_data = map(mapfunc_smd, runList)
    else:
        MAXNODES = 14
        pool = ProcessingPool(nodes=min(MAXNODES, len(runList)))
        run_data = pool.map(mapfunc, runList)
        #run_data = map(mapfunc, runList)

    event_data = {}
    runindx = 0
    for signal_increment, bg_increment, event_data_entry in run_data:
        try:
            signal += (signal_increment / len(runList))
        except UnboundLocalError:
            signal = signal_increment / len(runList)
        try:
            bg += (bg_increment / len(runList))
        except UnboundLocalError:
            bg = bg_increment / len(runList)
        event_data[runList[runindx]] = event_data_entry
        runindx += 1
        #event_data.append(event_data_entry)
    return signal, bg, event_data

def get_signal_bg_many_apply_default_bg(runList, detid, default_bg = None,
override_bg = None, event_data_getter = None, event_mask = None, **kwargs):
    """
    Wraps get_signal_bg_many, additionally allowing a default background 
    subtraction for groups of runs that lack interposed blank frames

    Inputs:
        default_bg: A list of run numbers to use for bg subtraction of 60Hz runs
        override_bg: A list of run numbers to use for bg subtraction of ALL
        runs

    If both default_bg and override_bg are provided, override_bg is used
    """
    signal, bg, event_data = get_signal_bg_many_parallel(runList, detid,
        event_data_getter = event_data_getter, event_mask = event_mask, **kwargs)
    if override_bg:
        discard, bg, event_data = get_signal_bg_many_parallel(override_bg, detid,
            event_data_getter = event_data_getter, event_mask = event_mask, **kwargs)
    # if a default background runs are supplied AND bg is all zeros (meaning
    # dummy values were inserted by get_signal_bg_many)
    elif default_bg and not np.any(bg):
        discard, bg, event_data = get_signal_bg_many_parallel(default_bg, detid,
            event_data_getter = event_data_getter, event_mask = event_mask, **kwargs)
    return signal, bg, event_data

#def process_and_save(runList, detid, **kwargs):
#    print "processing runs", runList
#    signal, bg = get_signal_bg_many(runList, detid, **kwargs)
#    boundaries = map(str, [runList[0], runList[-1]])
#    os.system('mkdir -p processed/')
#    np.savetxt("./processed/" + "-".join(boundaries) + "_" + str(detid) + "_bg.dat", bg)   
#    np.savetxt("./processed/" + "-".join(boundaries) + "_" + str(detid) + "_signal.dat", signal)
#    np.savetxt("./processed/" + "-".join(boundaries) + "_" + str(detid) + "_bgsubbed.dat", signal - bg)   
#    return signal, bg

