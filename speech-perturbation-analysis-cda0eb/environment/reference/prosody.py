
# -*- coding: utf-8 -*-
"""
Created on Jul 21 2017, Modified Apr 10 2018.

@author: J. C. Vasquez-Correa, T. Arias-Vergara, J. S. Guerrero
"""



import matplotlib.pyplot as plt
import numpy as np
from tqdm import tqdm
import torch
import pandas as pd
import pysptk
from matplotlib import cm
from scipy.io.wavfile import read
import os
import sys
PATH = os.path.dirname(os.path.realpath(__file__))

sys.path.append(PATH+'/../')
sys.path.append(PATH)

plt.rcParams["font.family"] = "Times New Roman"
from prosody_functions import V_UV, F0feat, energy_cont_segm, polyf0, energy_feat, dur_seg, duration_feat, get_energy_segment

from script_mananger import script_manager
from disvoice_utils import save_dict_kaldimat, get_dict
import praat.praat_functions as praat_functions
class Prosody:
    """
    Compute prosody features from continuous speech based on duration, fundamental frequency and energy.
    Static or dynamic matrices can be computed:
    Static matrix is formed with 103 features and include

    1-6     F0-contour:                                                       Avg., Std., Max., Min., Skewness, Kurtosis

    7-12    Tilt of a linear estimation of F0 for each voiced segment:        Avg., Std., Max., Min., Skewness, Kurtosis

    13-18   MSE of a linear estimation of F0 for each voiced segment:         Avg., Std., Max., Min., Skewness, Kurtosis

    19-24   F0 on the first voiced segment:                                   Avg., Std., Max., Min., Skewness, Kurtosis

    25-30   F0 on the last voiced segment:                                    Avg., Std., Max., Min., Skewness, Kurtosis

    31-34   energy-contour for voiced segments:                               Avg., Std., Skewness, Kurtosis

    35-38   Tilt of a linear estimation of energy contour for V segments:     Avg., Std., Skewness, Kurtosis

    39-42   MSE of a linear estimation of energy contour for V segment:       Avg., Std., Skewness, Kurtosis

    43-48   energy on the first voiced segment:                               Avg., Std., Max., Min., Skewness, Kurtosis

    49-54   energy on the last voiced segment:                                Avg., Std., Max., Min., Skewness, Kurtosis

    55-58   energy-contour for unvoiced segments:                             Avg., Std., Skewness, Kurtosis

    59-62   Tilt of a linear estimation of energy contour for U segments:     Avg., Std., Skewness, Kurtosis

    63-66   MSE of a linear estimation of energy contour for U segments:      Avg., Std., Skewness, Kurtosis

    67-72   energy on the first unvoiced segment:                             Avg., Std., Max., Min., Skewness, Kurtosis

    73-78   energy on the last unvoiced segment:                              Avg., Std., Max., Min., Skewness, Kurtosis

    79      Voiced rate:                                                      Number of voiced segments per second

    80-85   Duration of Voiced:                                               Avg., Std., Max., Min., Skewness, Kurtosis

    86-91   Duration of Unvoiced:                                             Avg., Std., Max., Min., Skewness, Kurtosis

    92-97   Duration of Pauses:                                               Avg., Std., Max., Min., Skewness, Kurtosis

    98-103  Duration ratios:                                                 Pause/(Voiced+Unvoiced), Pause/Unvoiced, Unvoiced/(Voiced+Unvoiced),Voiced/(Voiced+Unvoiced), Voiced/Puase, Unvoiced/Pause

    Dynamic matrix is formed with 13 features computed for each voiced segment and contains


    1-6. Coefficients of 5-degree Lagrange polynomial to model F0 contour

    7-12. Coefficients of 5-degree Lagrange polynomial to model energy contour

    13. Duration of the voiced segment

    Dynamic prosody features are based on
    Najim Dehak, "Modeling Prosodic Features With Joint Factor Analysis for Speaker Verification", 2007

    Script is called as follows

    >>> python prosody.py <file_or_folder_audio> <file_features> <static (true or false)> <plots (true or false)> <format (csv, txt, npy, kaldi, torch)>

    Examples directly in Python

    >>> prosody=Prosody()
    >>> file_audio="../audios/001_ddk1_PCGITA.wav"
    >>> features1=prosody.extract_features_file(file_audio, static=True, plots=True, fmt="npy")

    """

    def __init__(self):
        self.pitch_method = "rapt"
        self.size_frame = 0.02
        self.step = 0.01
        self.thr_len = 0.14
        self.minf0 = 60
        self.maxf0 = 350
        self.voice_bias = -0.2
        self.P = 5
        self.namefeatf0 = ["F0avg", "F0std", "F0max", "F0min",
                           "F0skew", "F0kurt", "F0tiltavg", "F0mseavg",
                           "F0tiltstd", "F0msestd", "F0tiltmax", "F0msemax",
                           "F0tiltmin", "F0msemin", "F0tiltskw", "F0mseskw",
                           "F0tiltku", "F0mseku", "1F0mean", "1F0std",
                           "1F0max", "1F0min", "1F0skw", "1F0ku", "lastF0avg",
                           "lastF0std", "lastF0max", "lastF0min", "lastF0skw", "lastF0ku"]
        self.namefeatEv = ["avgEvoiced", "stdEvoiced", "skwEvoiced", "kurtosisEvoiced",
                           "avgtiltEvoiced", "stdtiltEvoiced", "skwtiltEvoiced", "kurtosistiltEvoiced",
                           "avgmseEvoiced", "stdmseEvoiced", "skwmseEvoiced", "kurtosismseEvoiced",
                           "avg1Evoiced", "std1Evoiced", "max1Evoiced", "min1Evoiced", "skw1Evoiced",
                           "kurtosis1Evoiced", "avglastEvoiced", "stdlastEvoiced", "maxlastEvoiced",
                           "minlastEvoiced", "skwlastEvoiced",  "kurtosislastEvoiced"]
        self.namefeatEu = ["avgEunvoiced", "stdEunvoiced", "skwEunvoiced", "kurtosisEunvoiced",
                           "avgtiltEunvoiced", "stdtiltEunvoiced", "skwtiltEunvoiced", "kurtosistiltEunvoiced",
                           "avgmseEunvoiced", "stdmseEunvoiced", "skwmseEunvoiced", "kurtosismseEunvoiced",
                           "avg1Eunvoiced", "std1Eunvoiced", "max1Eunvoiced", "min1Eunvoiced", "skw1Eunvoiced",
                           "kurtosis1Eunvoiced", "avglastEunvoiced", "stdlastEunvoiced", "maxlastEunvoiced",
                           "minlastEunvoiced", "skwlastEunvoiced",  "kurtosislastEunvoiced"]

        self.namefeatdur = ["Vrate", "avgdurvoiced", "stddurvoiced", "skwdurvoiced", "kurtosisdurvoiced", "maxdurvoiced", "mindurvoiced",
                            "avgdurunvoiced", "stddurunvoiced", "skwdurunvoiced", "kurtosisdurunvoiced", "maxdurunvoiced", "mindurunvoiced",
                            "avgdurpause", "stddurpause", "skwdurpause", "kurtosisdurpause", "maxdurpause", "mindurpause",
                            "PVU", "PU", "UVU", "VVU", "VP", "UP"]
        self.head_st = self.namefeatf0+self.namefeatEv+self.namefeatEu+self.namefeatdur

        self.namef0d = ["f0coef"+str(i) for i in range(6)]
        self.nameEd = ["Ecoef"+str(i) for i in range(6)]
        self.head_dyn = self.namef0d+self.nameEd+["Voiced duration"]

    def prosody_static(self, audio, plots):
        """Extract the static prosody features from an audio file

        :param audio: .wav audio file.
        :param plots: timeshift to extract the features
        :returns: array with the 103 prosody features

        >>> prosody=Prosody()
        >>> file_audio="../audios/001_ddk1_PCGITA.wav"
        >>> features=prosody.prosody_static(file_audio, plots=True)

        """
        fs, data_audio = read(audio)

        if len(data_audio.shape)>1:
            data_audio = data_audio.mean(1)
        data_audio = data_audio-np.mean(data_audio)
        data_audio = data_audio/float(np.max(np.abs(data_audio)))
        size_frameS = self.size_frame*float(fs)
        size_stepS = self.step*float(fs)
        thr_len_pause = self.thr_len*float(fs)

        if self.pitch_method == 'praat':
            name_audio = audio.split('/')
            temp_uuid = 'prosody'+name_audio[-1][0:-4]
            if not os.path.exists(PATH+'/../tempfiles/'):
                os.makedirs(PATH+'/../tempfiles/')
            temp_filename_f0 = PATH+'/../tempfiles/tempF0'+temp_uuid+'.txt'
            temp_filename_vuv = PATH+'/../tempfiles/tempVUV'+temp_uuid+'.txt'
            praat_functions.praat_vuv(audio, temp_filename_f0, temp_filename_vuv,
                                      time_stepF0=self.step, minf0=self.minf0, maxf0=self.maxf0)

            F0, _ = praat_functions.decodeF0(
                temp_filename_f0, len(data_audio)/float(fs), self.step)
            os.remove(temp_filename_f0)
            os.remove(temp_filename_vuv)
        elif self.pitch_method == 'rapt':
            data_audiof = np.asarray(data_audio*(2**15), dtype=np.float32)
            F0 = pysptk.sptk.rapt(data_audiof, fs, int(
                size_stepS), min=self.minf0, max=self.maxf0, voice_bias=self.voice_bias, otype='f0')

        segmentsV = V_UV(F0, data_audio, type_seg="Voiced",
                         size_stepS=size_stepS)
        segmentsUP = V_UV(F0, data_audio, type_seg="Unvoiced",
                          size_stepS=size_stepS)

        segmentsP = []
        segmentsU = []
        for k in range(len(segmentsUP)):
            if (len(segmentsUP[k]) > thr_len_pause):
                segmentsP.append(segmentsUP[k])
            else:
                segmentsU.append(segmentsUP[k])

        F0_features = F0feat(F0)
        energy_featuresV = energy_feat(segmentsV, fs, size_frameS, size_stepS)
        energy_featuresU = energy_feat(segmentsU, fs, size_frameS, size_stepS)
        duration_features = duration_feat(
            segmentsV, segmentsU, segmentsP, data_audio, fs)

        features = np.hstack(
            (F0_features, energy_featuresV, energy_featuresU, duration_features))

        return features

    def prosody_dynamic(self, audio):
        """Extract the dynamic prosody features from an audio file

        :param audio: .wav audio file.
        :returns: array (N,13) with the prosody features extracted from an audio file.  N= number of voiced segments

        >>> prosody=Prosody()
        >>> file_audio="../audios/001_ddk1_PCGITA.wav"
        >>> features=prosody.prosody_dynamic(file_audio)

        """
        fs, data_audio = read(audio)

        if len(data_audio.shape)>1:
            data_audio = data_audio.mean(1)
        data_audio = data_audio-np.mean(data_audio)
        data_audio = data_audio/float(np.max(np.abs(data_audio)))
        size_frameS = self.size_frame*float(fs)
        size_stepS = self.step*float(fs)
        overlap = size_stepS/size_frameS

        if self.pitch_method == 'praat':
            name_audio = audio.split('/')
            temp_uuid = 'prosody'+name_audio[-1][0:-4]
            if not os.path.exists(PATH+'/../tempfiles/'):
                os.makedirs(PATH+'/../tempfiles/')
            temp_filename_f0 = PATH+'/../tempfiles/tempF0'+temp_uuid+'.txt'
            temp_filename_vuv = PATH+'/../tempfiles/tempVUV'+temp_uuid+'.txt'
            praat_functions.praat_vuv(audio, temp_filename_f0, temp_filename_vuv,
                                      time_stepF0=self.step, minf0=self.minf0, maxf0=self.maxf0)

            F0, _ = praat_functions.decodeF0(
                temp_filename_f0, len(data_audio)/float(fs), self.step)
            os.remove(temp_filename_f0)
            os.remove(temp_filename_vuv)
        elif self.pitch_method == 'rapt':
            data_audiof = np.asarray(data_audio*(2**15), dtype=np.float32)
            F0 = pysptk.sptk.rapt(data_audiof, fs, int(
                size_stepS), min=self.minf0, max=self.maxf0, voice_bias=self.voice_bias, otype='f0')

        pitchON = np.where(F0 != 0)[0]
        dchange = np.diff(pitchON)
        change = np.where(dchange > 1)[0]
        iniV = pitchON[0]

        featvec = []
        iniVoiced = (pitchON[0]*size_stepS)+size_stepS
        seg_voiced = []
        f0v = []
        Ev = []
        for indx in change:
            finV = pitchON[indx]+1
            finVoiced = (pitchON[indx]*size_stepS)+size_stepS
            VoicedSeg = data_audio[int(iniVoiced):int(finVoiced)]
            temp = F0[iniV:finV]
            tempvec = []
            if len(VoicedSeg) > int(size_frameS):
                seg_voiced.append(VoicedSeg)
                dur = len(VoicedSeg)/float(fs)
                x = np.arange(0,len(temp))
                z = np.poly1d(np.polyfit(x,temp,self.P))
                f0v.append(temp)
                tempvec.extend(z.coeffs)
                temp=get_energy_segment(size_frameS, size_stepS, VoicedSeg, overlap)
                Ev.append(temp)
                x = np.arange(0, len(temp))
                z = np.poly1d(np.polyfit(x, temp, self.P))
                tempvec.extend(z.coeffs)
                tempvec.append(dur)
                featvec.append(tempvec)
            iniV = pitchON[indx+1]
            iniVoiced = (pitchON[indx+1]*size_stepS)+size_stepS

        # Add the last voiced segment
        finV = (pitchON[len(pitchON)-1])
        finVoiced = (pitchON[len(pitchON)-1]*size_stepS)+size_stepS
        VoicedSeg = data_audio[int(iniVoiced):int(finVoiced)]
        temp = F0[iniV:finV]
        tempvec = []

        if len(VoicedSeg) > int(size_frameS):
            dur = len(VoicedSeg)/float(fs)

            x = np.arange(0, len(temp))
            z = np.poly1d(np.polyfit(x, temp, self.P))
            tempvec.extend(z.coeffs)
            temp=get_energy_segment(size_frameS, size_stepS, VoicedSeg, overlap)
            x = np.arange(0, len(temp))
            z = np.poly1d(np.polyfit(x, temp, self.P))
            tempvec.extend(z.coeffs)
            tempvec.append(dur)
            featvec.append(tempvec)

        return np.asarray(featvec)
