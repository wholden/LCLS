#!/usr/bin/env python

import sys
import argparse
import numpy as np
import math
import matplotlib.pyplot as plt
import matplotlib as mp
import os
from scipy import interpolate

from dataccess import data_access as data
from dataccess import xes_energies

import dill
from dataccess import utils
import pdb
from scipy.ndimage.filters import gaussian_filter as filt


#set matplotlib linewidth parameters
#mp.rcParams['axes.linewidth'] = .3
#mp.rcParams['lines.linewidth'] = .3
#mp.rcParams['patch.linewidth'] = .3

# backsatter energy for graphite 002
e0 = 1848.303414

# elements and their emission energies
# TODO: test the most recent changes
# TODO: extend this to all other elements
elements = ["Sc","Ti","V","Cr","Mn","Fe","Co","Ni"]

# Dict of emission line energies. 
# Format: emission[eltname][line id] = photon energy
emission = xes_energies.emission_dict()

# Maps emission line keys to plot labels
lineidforplot = {'ka1': "$K\\alpha_1$", 'ka2': "$K\\alpha_2$", 'kb': "$K\\beta_{1,3}$", 'Ef': "$E_F$"}

def center_col(label, detid, run_label_filename = 'labels.txt'):
    """
    Return the peak index of the label data summed along the zeroth axis
    (perpendicular to the energy-dispersive direction
    """
    summed = np.sum(data.get_label_data(label, detid, fname = run_label_filename), axis = 0)
    return np.argmax(summed)

def lineout(label, detid, cencol, pxwidth = 10, default_bg = None, run_label_filename = 'labels.txt'):
    """
    Return a 1d lineout
    """
    raw = data.get_label_data(label, detid, default_bg = default_bg, fname = run_label_filename)
    frame_dimension = len(raw)
    spectrum_intensities = np.array([ sum( [raw[i][j] for j in range(cencol-pxwidth,cencol+pxwidth+1)] ) for i in range(frame_dimension) ])
    return spectrum_intensities

def get_normalization(x, intensities, sumwidth = 150):
    nalpha = np.argmax(intensities)
    x_alpha = x[nalpha]
    filtered = intensities[np.logical_and(x > x_alpha - sumwidth, x < x_alpha + sumwidth)]
    print "peak index: ", nalpha
    return np.sum(filtered)
    #return np.sum(intensities[max(nalpha-sumwidth,0):min(nalpha+sumwidth,len(intensities) - 1)])

def mask_peaks_and_iterpolate(x, y, peak_ranges, avg_interval = 20.):
    interpolationx = []
    interpolationy = []
    for peakmin, peakmax in peak_ranges:
        indices_min = np.where(np.abs(x - peakmin) < avg_interval)[0]
        ymin = [np.mean(y[indices_min])] * len(indices_min)
        xmin = list(x[indices_min])

        indices_max = np.where(np.abs(x - peakmax) < avg_interval)[0]
        ymax = [np.mean(y[indices_max])] * len(indices_max)
        xmax = list(x[indices_max])

        interpolationx += (xmin + xmax)
        interpolationy += (ymin + ymax)
        
#        good_indices = np.where(np.logical_or(x < peakmin, x > peakmax))[0]
#        y = y[good_indices]
#        x = x[good_indices]
    return utils.extrap1d(interpolate.interp1d(np.array(interpolationx), np.array(interpolationy)))

def linear_bg_subtraction(x, y, peak_ranges):
    bg = mask_peaks_and_iterpolate(x, y, peak_ranges)
    plt.plot(x, bg(x))
    return y - bg(x)

def peak_sizes(x, y, peak_ranges, bg_subtract = True):
    backgnd = mask_peaks_and_iterpolate(x, y, peak_ranges)
    if bg_subtract is True:
        subtracted = y - backgnd(x)
    else:
        subtracted = y
    sizeList = []
    for peakmin, peakmax in peak_ranges:
        peakIndices = np.where(np.logical_and(x >= peakmin, x <= peakmax))[0]
        sizeList += [np.sum(subtracted[peakIndices])]
    return sizeList

def save_calib(fname, energies):
    with open(fname, 'wb') as f:
        np.savetxt(f, np.array([range(len(energies)), energies]).T, header = 'row index\tenergy(eV)')

def load_calib(fname):
    with open(fname, 'rb') as f:
        energies =(np.genfromtxt(f).T)[1]
    return energies
    

def get_energies(label, detid, eltname, cencol, save_path = None, run_label_filename = 'labels.txt', **kwargs):
    """
    Return 1d array of energies corresponding to rows on the detector 
    based on calibration off of the ka and kb positions in XES data of the 
    given label and detid (1 or 2)

    If a string is assigned to save_path, the calibration is saved under
        that given name in the directory calibs/

    Returns a tuple:
    Row index of the k alpha peak, 1d array of energies
    """
    if detid not in [1, 2]:
        raise ValueError("Invalid detector id for von Hamos spectrometer")

    # element id
    kalpha = emission[eltname]['ka1']
    kbeta = emission[eltname]['kb']

    spectrum = lineout(label, detid, cencol, run_label_filename = run_label_filename)[::-1]
    frame_dimension = len(spectrum)
    nalpha = np.argmax(spectrum)
    offset = nalpha + 20
    nbeta = np.argmax(spectrum[offset:]) + offset

    # calculate position of peak positions on spectrometer
    thalpha = math.asin(e0/kalpha)
    posalpha = 103.4/(math.tan(thalpha))
    thbeta = math.asin(e0/kbeta)
    posbeta = 103.4/(math.tan(thbeta))

    # calculate pixel size
    pxsize = (posbeta - posalpha)/(nalpha - nbeta)

    # calculate pixel positions
    pixels = range(nalpha,nalpha-frame_dimension,-1)
    pixels = [ posalpha + pxsize*n for n in pixels ]

    # calculate Bragg angles and energies for graphite 002
    thetalist = [ math.atan(103.4/p) for p in pixels ]
    elist = [ 1848.303414/(math.sin(theta)) for theta in thetalist ]

    nrm = np.sum(spectrum[max(nalpha-40,0):min(nalpha+40,frame_dimension)])
    energies = elist[::-1]
    if save_path and os.path.dirname(save_path):
        os.system('mkdir -p ' + os.path.dirname(save_path))
        save_calib(save_path, energies)
    return np.array(energies)

# TODO: allow masking out bad data ranges (probably something to put into
#  a config file) for background subtraction purposes
def get_spectrum_one_label(eltname, detid, label, cold_calibration_label, \
        cencol_calibration_label, pxwidth = 10, default_bg = None,\
        bg_sub = True, calib_load_path = None,\
        calib_save_path = None, kalpha_kbeta_calibration = True,
        run_label_filename = 'labels.txt'):
    """
    Return the XES spectrum corresponding to the given label, detector ID, 
    and element

    Inputs:
        eltname: string of the abbreviated element name
        detid: CSPAD detector ID (1 or 2)
        label: string reference to a group of runs
        cold_calibration_label: label to use for determination of the energy
            scale
        cencol_calibration_label: label to use for location of the
            spectrometer's line of focus
        pxwidth: width of the CSPAD lineout from which the spectrum is
            constructed
        default_bg: label to use for background subtraction if embedded blank
            frames are missing
        peak_width:
            TODO: deprecate or not?
        bg_sub: if True, perform a constant subtraction. The subtracted
            constant is the 5th percentile of the spectrum after smoothing
            with a gaussian kernel of standard deviation 5
        calib_load_path: path to a file with an energy calibration to load
        calib_save_path: File to which to save an energy calibration if
            calib_load_path is None
        kalpha_kbeta_calibration: If calib_load_path is None, use k alpha
            and k beta peak locations to determine an energy scale. If None
            and calib_load_path is also None, do not perform an energy
            calibration at all.
    Output: array, array -> energy or index, normalized intensity
    """
    if kalpha_kbeta_calibration or calib_load_path:
        peak_width = 150
    else:
        peak_width = 15
    cencol = center_col(cencol_calibration_label, detid, run_label_filename =run_label_filename )
    intensities = lineout(label, detid, cencol, pxwidth = pxwidth, default_bg = default_bg, run_label_filename = run_label_filename)
    if calib_load_path:
        x = load_calib(calib_load_path)
    elif kalpha_kbeta_calibration:
        x = get_energies(cold_calibration_label, detid, eltname, cencol, save_path = calib_save_path, run_label_filename = run_label_filename)
    else:
        x = np.array(range(len(intensities)))
#    if lin_bg_sub:
#        peak_ranges = [[e - peak_width, e + peak_width] for e in emission[eltname]]
#        intensities = linear_bg_subtraction(x, intensities, peak_ranges)
    if bg_sub:
        smoothed = filt(intensities, 5)
        floor = np.percentile(smoothed, 5)
        intensities -= floor
    norm = get_normalization(x, intensities, peak_width)
    #plt.plot(x, smoothed/norm)
    return x, intensities / norm

def main(eltname, detid, labels, cold_calibration_label, \
        cencol_calibration_label, pxwidth = 10, default_bg = None,
        calib_load_path = None, calib_save_path = None,\
        kalpha_kbeta_calibration = True,
        run_label_filename = 'labels.txt'):
    spectrumList = []
    if not os.path.exists('xes/'):
        os.makedirs('xes')
    for label in labels:
        energies, intensities = get_spectrum_one_label(eltname, detid, label,\
            cold_calibration_label, cencol_calibration_label, pxwidth = pxwidth,\
            default_bg = default_bg, calib_load_path = calib_load_path,\
            calib_save_path = calib_save_path,\
            kalpha_kbeta_calibration = kalpha_kbeta_calibration,
            run_label_filename = run_label_filename)
        spectrumList.append([energies, intensities])
        np.savetxt('xes/' + label + '_' + eltname + '_' + str(detid),
[energies, intensities], header = 'energy (eV)\tintensity (arb)')
    name = 'plots_xes/' + '_'.join(labels) + '_' + eltname + '_' + str(detid)
    plot_spectra(eltname, spectrumList, labels, name)


# TODO: Fix the behavior for the case in which the spectra aren't energy-
# calibrated
def plot_spectra(eltname, spectrumList, labels, name = None):
    if not os.path.exists('plots_xes/'):
        os.makedirs('plots_xes/')
    elist = spectrumList[0][0]
    max_intensity = np.max(map(lambda x: x[1], spectrumList))
    plt.plot(elist, spectrumList[0][1], label = labels[0])
    plt.axhline(y=0, color = "black")
    plt.title(eltname + " XES")

    #add vertical lines to identify peaks within observed range
    txtshift = {'ka1': 0, 'ka2': -20, 'kb': -25, 'Ef': 0}
    txtheight = {'ka1': 1.1, 'ka2': 1.1, 'kb': 0.5, 'Ef': 0.5}
    lines = emission[eltname].keys()
    for line in lines:
        if elist[-1] - 50 < emission[eltname][line] < elist[0] + 50:
            plt.plot( [emission[eltname][line], emission[eltname][line]],
                [(-0.05)*max_intensity, (txtheight[line])*max_intensity],
                color = "gray")
            plt.text(emission[eltname][line]+txtshift[line], (txtheight[line])*max_intensity, lineidforplot[line], size="large")

    colorlist = 4 * ["orange", "green", "purple", "red", "brown", "black"]
    ncolors = len(colorlist)

    for spectrum, label, n in zip(spectrumList[1:], labels[1:], range(len(labels[1:]))):
        plt.plot(spectrum[0], spectrum[1], label = label, color = colorlist[(n-1)])

    plt.legend()
    plt.xlabel("Energy (eV)", size="large")
    plt.ylabel("Counts", size="large")
    plt.ylim((0, 1.15 * max_intensity))
    if name:
        plt.savefig(name + '.png', bbox_inches='tight')
        plt.savefig(name + '.svg', bbox_inches='tight')
    plt.show()


if __name__ =='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('eltname', help = 'Element name.')
    parser.add_argument('detid', type = int, help = 'Detector ID.')
    parser.add_argument('calibration', type = str, help = 'Label of a group of runs to use for calibration of the energy scale (if a calibration file is not provided) and identification of the subregion of the CSPAD to process into a spectrum.')
    parser.add_argument('--pxwidth', '-p', type = int, default = 10, help = 'Pixel width of CSPAD subregion to sum.')
    parser.add_argument('--background', '-b',  help = 'Use runs of this label for background subtraction instead of extracting dark exposures from the run, if interposed background frames are absent.')
    parser.add_argument('--calibration_save_path', '-s', type = str, help = 'Path to which to save energy calibration data if calibration_load_path is unspecified and --kalpha_kbeta_calibration is selected.')
    parser.add_argument('--calibration_load_path', '-l', type = str, help = 'Path from which to load energy calibration data')
    parser.add_argument('--kalpha_kbeta_calibration', '-k', action = 'store_true', help = 'Enable automaic generation of energy calibration based on k alpha and k beta peak locations if --calibration_load_path is not given.')
    parser.add_argument('--runlabels', '-r', type = str, default = 'labels.txt', help = 'Path to run group label input file. Defaults to labels.txt. If the file does not exist it is generated automatically (based on run data timestamps), and can subsequently be edited by the user.)')
    parser.add_argument('datalabels', nargs = '+', help = 'Labels of run groups to process.')
    args = parser.parse_args()
    eltname = args.eltname
    cold_calibration_label = args.calibration
    cencol_calibration_label = args.calibration
    pxwidth = args.pxwidth
    default_bg = args.background
    detid = args.detid
    labels = args.datalabels
    pxwidth = args.pxwidth
    calibration_save_path = args.calibration_save_path
    calibration_load_path = args.calibration_load_path
    kalpha_kbeta_calibration = args.kalpha_kbeta_calibration
    main(eltname, detid, labels, cold_calibration_label, \
        cencol_calibration_label, pxwidth = pxwidth, default_bg = default_bg,\
        calib_save_path = calibration_save_path, calib_load_path =\
        calibration_load_path, kalpha_kbeta_calibration = kalpha_kbeta_calibration,
        run_label_filename = args.runlabels)
