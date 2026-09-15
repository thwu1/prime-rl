import math
import numpy as np
import numpy.matlib as matlib
from scipy.stats import skew, kurtosis

class FeatureExtractor:
    """
    Feature extraction class including feature groups, feature list, and feature extraction code.
    """
    def get_feature_groups(self):
        """Gets a list of all available feature groups.

        Returns
        ----------
        dictionary
            A dictionary with the all available feature groups and their respective features.
        """
        feature_groups = {'HTD': ['MAV', 'ZC', 'SSC', 'WL'],
                          'TSTD': ['MAVFD','DASDV','WAMP','ZC','MFL','SAMPEN','M0','M2','M4','SPARSI','IRF','WLF'],
                          'HJORTH': ['ACT','MOB','COMP'],
                          'LS4': ['LS', 'MFL', 'MSR', 'WAMP'],
                          'LS9': ['LS', 'MFL', 'MSR', 'WAMP', 'ZC', 'RMS', 'IAV', 'DASDV', 'VAR'],
                          'TDPSD': ['M0','M2','M4','SPARSI','IRF','WLF'],
                          'ITD': ['ISD','COR','MDIFF','MLK'],
                          }
        return feature_groups

    def get_feature_list(self):
        """Gets a list of all available features.

        Returns
        ----------
        list
            A list of all available features.
        """
        feature_list = ['MAV',
                        'ZC',
                        'SSC',
                        'WL',
                        'LS',
                        'MFL',
                        'MSR',
                        'WAMP',
                        'RMS',
                        'IAV',
                        'DASDV',
                        'VAR',
                        'M0',
                        'M2',
                        'M4',
                        'SPARSI',
                        'IRF',
                        'WLF',
                        'LD',
                        'MAVFD',
                        'MDF',
                        'MNF',
                        'MNP',
                        'MPK',
                        'SKEW',
                        'KURT',
                        "PAP",
                        "MZP",
                        "TM",
                        "SM",
                        "SAMPEN",
                        "FUZZYEN",
                        "ISD",
                        "COR",
                        "MDIFF",
                        "MLK",
                        "ACT",
                        "MOB",
                        "COMP",
                        "MEAN"]
        return feature_list

    def extract_feature_group(self, feature_group, windows, feature_dic={}):
        """Extracts a group of features.

        Parameters
        ----------
        feature_group: string
            The group of features to extract.
        windows: list
            A list of windows - should be computed directly from the OfflineDataHandler or the utils.get_windows() method.
        feature_dic: dict
            A dictionary containing the parameters you'd like passed to each feature.

        Returns
        ----------
        dictionary
            A dictionary where each key is a specific feature and its value is a list of the computed
            features for each window.
        """
        features = {}
        if not feature_group in self.get_feature_groups():
            return features
        feats = self.extract_features(self.get_feature_groups()[feature_group], windows, feature_dic)
        return feats

    def extract_features(self, feature_list, windows, feature_dic={}):
        """Extracts a list of features.

        Parameters
        ----------
        feature_list: list
            The group of features to extract.
        windows: list
            A list of windows - should be computed directly from the OfflineDataHandler or the utils.get_windows() method.
        feature_dic: dict
            A dictionary containing the parameters you'd like passed to each feature. ex. {"MDF_sf":1000}

        Returns
        ----------
        dictionary
            A dictionary where each key is a specific feature and its value is a list of the computed
            features for each window.
        """
        features = {}
        for feature in feature_list:
            if feature in self.get_feature_list():
                method_to_call = getattr(self, 'get' + feature + 'feat')
                valid_keys = [i for i in list(feature_dic.keys()) if feature+"_" in i]
                smaller_dictionary = dict((k, feature_dic[k]) for k in valid_keys if k in feature_dic)
                feats = method_to_call(windows, **smaller_dictionary)
                features[feature] = feats
        return features

    def check_features(self, features, silent=False):
        """Assesses a features object for np.nan, np.inf, and -np.inf.

        Parameters
        ----------
        features: np.ndarray or dict
            A group of features extracted with the feature extraction package.
        silent: bool (default=False)
            If True, will silence all prints from this function.

        Returns
        ----------
        violations: int
            A number of violations found within the data.
        """
        violations = 0
        if type(features) == dict:
            feature_list = list(features.keys())
            for fk in feature_list:
                if (features[fk] == np.nan).any():
                    violations += 1
                if (features[fk] == np.inf).any():
                    violations += 1
                if (features[fk] == -1*np.inf).any():
                    violations += 1
        elif type(features) == np.ndarray:
            if (features == np.nan).any():
                violations += 1
            if (features == np.inf).any():
                violations += 1
            if (features == -1*np.inf).any():
                violations += 1
        return violations

    '''
    -----------------------------------------------------------------------------------------
    The following methods are all feature extraction methods. They should follow the same
    format that already exists (i.e., get<FEAT_ABBREVIATION>feat). The feature abbreviation
    should be added to the get feature_list function.
    '''

    def getMAVfeat(self, windows):
        """Extract Mean Absolute Value (MAV) feature."""
        feat = np.mean(np.abs(windows),2)
        return feat

    def getMEANfeat(self, windows):
        """Extract mean of signal (MEAN) feature."""
        return np.mean(windows, -1)

    def getZCfeat(self, windows):
        """Extract Zero Crossings (ZC) feature."""
        sgn_change = np.diff(np.sign(windows),axis=2)
        neg_change = sgn_change == -2
        pos_change = sgn_change ==  2
        feat_a = np.sum(neg_change,2)
        feat_b = np.sum(pos_change,2)
        return feat_a+feat_b

    def getSSCfeat(self, windows,SSC_threshold=0.0):
        """Extract Slope Sign Change (SSC) feature."""
        assert type(SSC_threshold) == float
        w_2 = windows[:,:,2:]
        w_1 = windows[:,:,1:-1]
        w_0 = windows[:,:,:-2]
        con = (((w_1-w_0)*(w_1-w_2)) >= SSC_threshold)
        return np.sum(con,axis=2)

    def getWLfeat(self, windows):
        """Extract Waveform Length (WL) feature."""
        feat = np.sum(np.abs(np.diff(windows,axis=2)),2)
        return feat

    def getLSfeat(self, windows):
        """Extract L-Score (LS) feature."""
        feat = np.zeros((windows.shape[0],windows.shape[1]))
        for w in range(0, windows.shape[0],1):
            for c in range(0, windows.shape[1],1):
                tmp = self.__lmom(np.reshape(windows[w,c,:],(1,windows.shape[2])),2)
                feat[w,c] = tmp[0,1]
        return feat

    def __lmom(self, signal, nL):
        b = np.zeros((1,nL-1))
        l = np.zeros((1,nL-1))
        b0 = np.zeros((1,1))
        b0[0,0] = np.mean(signal)
        n = signal.shape[1]
        signal = np.sort(signal, axis=1)
        for r in range(1,nL,1):
            num = np.tile(np.asarray(range(r+1,n+1)),(r,1))  - np.tile(np.asarray(range(1,r+1)),(1,n-r))
            num = np.prod(num,axis=0)
            den = np.tile(np.asarray(n),(1,r)) - np.asarray(range(1,r+1))
            den = np.prod(den)
            b[r-1] = 1/n * np.sum(num / den * signal[0,r:n])
        tB = np.concatenate((b0,b))
        B = np.flip(tB,0)
        for i in range(1, nL, 1):
            Spc = np.zeros((B.shape[0]-(i+1),1))
            Coeff = np.concatenate((Spc, self.__LegendreShiftPoly(i)))
            l[0,i-1] = np.sum(Coeff * B)
        L = np.concatenate((b0, l),1)
        return L

    def __LegendreShiftPoly(self, n):
        pk = np.zeros((n+1,1))
        if n == 0:
            pk = 1
        elif n == 1:
            pk[0,0] = 2
            pk[1,0] = -1
        else:
            pkm2 = np.zeros(n+1)
            pkm2[n] = 1
            pkm1 = np.zeros(n+1)
            pkm1[n] = -1
            pkm1[n-1] = 2
            for k in range(2,n+1,1):
                pk = np.zeros((n+1,1))
                for e in range(n-k+1,n+1,1):
                    pk[e-1] = (4*k-2)*pkm1[e]+ (1-2*k)*pkm1[e-1] + (1-k) * pkm2[e-1]
                pk[n,0] = (1-2*k)*pkm1[n] + (1-k)*pkm2[n]
                pk = pk/k
                if k < n:
                    pkm2 = pkm1
                    pkm1 = pk
        return pk

    def getMFLfeat(self, windows):
        """Extract Maximum Fractal Length (MFL) feature."""
        feat = np.log10(np.sum(np.abs(np.diff(windows, axis=2)),axis=2))
        return feat

    def getMSRfeat(self, windows):
        """Extract Mean Squared Ratio (MSR) feature."""
        feat = np.abs(np.mean(np.sqrt(windows.astype('complex')),axis=2))
        return feat

    def getWAMPfeat(self, windows, WAMP_threshold=2e-3):
        """Extract Willison Amplitude (WAMP) feature."""
        assert type(WAMP_threshold) == float
        feat = np.sum(np.abs(np.diff(windows, axis=2)) > WAMP_threshold, axis=2)
        return feat

    def getRMSfeat(self, windows):
        """Extract Root Mean Square (RMS) feature."""
        feat = np.sqrt(np.mean(np.square(windows),2))
        return feat

    def getIAVfeat(self, windows):
        """Extract Integral of Absolute Value (IAV) feature."""
        feat = np.sum(np.abs(windows),axis=2)
        return feat

    def getDASDVfeat(self, windows):
        """Difference Absolute Standard Deviation Value (DASDV) feature."""
        feat = np.sqrt(np.mean(np.diff(windows,axis=2)**2,axis=2))
        return feat

    def getVARfeat(self, windows):
        """Extract Variance (VAR) feature."""
        feat = np.var(windows,axis=2)
        return feat

    def getM0feat(self, windows):
        """Extract First Temporal Moment (M0) feature."""

        def closure(w):
            m0 = np.sqrt(np.sum(w**2,axis=2))/(w.shape[2]-1)
            m0 = m0 ** 0.1 / 0.1
            return np.log(np.abs(m0))
        m0_ebp=closure(windows)
        m0_efp=closure(np.log(windows**2+np.spacing(1)))

        num=-2*np.multiply(m0_efp,m0_ebp)
        den=np.multiply(m0_efp, m0_efp) + np.multiply(m0_ebp, m0_ebp)

        #Feature extraction goes here
        return num/den

    def getM2feat(self, windows):
        """Extract Second Temporal Moment (M2) feature."""
        def closure(w):
            m0 = np.sqrt(np.sum(w**2,axis=2))/(w.shape[2]-1)
            m0 = m0 ** 0.1 / 0.1
            d1 = np.diff(w, n=1, axis=2)
            m2 = np.sqrt(np.sum(d1 **2, axis=2)/ (w.shape[2]-1))
            m2 = m2 ** 0.1 / 0.1
            return np.log(np.abs(m0-m2))
        m2_ebp=closure(windows)
        m2_efp=closure(np.log(windows**2+np.spacing(1)))

        num=-2*np.multiply(m2_efp,m2_ebp)
        den=np.multiply(m2_efp, m2_efp) + np.multiply(m2_ebp, m2_ebp)

        return num/den

    def getM4feat(self, windows):
        """Extract Fourth Temporal Moment (M4) feature."""
        def closure(w):
            m0 = np.sqrt(np.sum(w**2,axis=2))/(w.shape[2]-1)
            m0 = m0 ** 0.1 / 0.1
            d1 = np.diff(w, n=1, axis=2)
            d2 = np.diff(d1, n=1, axis=2)
            m4 = np.sqrt(np.sum(d2 **2, axis=2)/ (w.shape[2]-1))
            m4 = m4 ** 0.1 / 0.1
            return np.log(np.abs(m0-m4))
        m4_ebp=closure(windows)
        m4_efp=closure(np.log(windows**2+np.spacing(1)))

        num=-2*np.multiply(m4_efp,m4_ebp)
        den=np.multiply(m4_efp, m4_efp) + np.multiply(m4_ebp, m4_ebp)

        return num/den

    def getSPARSIfeat(self, windows):
        """Extract Sparsness (SPARSI) feature."""
        def closure(w):
            m0 = np.sqrt(np.sum(w**2,axis=2))/(w.shape[2]-1)
            m0 = m0 ** 0.1 / 0.1
            d1 = np.diff(w, n=1, axis=2)
            m2 = np.sqrt(np.sum(d1 **2, axis=2)/ (w.shape[2]-1))
            m2 = m2 ** 0.1 / 0.1
            d2 = np.diff(d1, n=1, axis=2)
            m4 = np.sqrt(np.sum(d2 **2, axis=2)/ (w.shape[2]-1))
            m4 = m4 ** 0.1 / 0.1
            sparsi = np.sqrt(np.abs((m0-m2)*(m0-m4)))/m0
            return np.log(np.abs(sparsi))
        sparsi_ebp=closure(windows)
        sparsi_efp=closure(np.log(windows**2+np.spacing(1)))

        num=-2*np.multiply(sparsi_efp,sparsi_ebp)
        den=np.multiply(sparsi_efp, sparsi_efp) + np.multiply(sparsi_ebp, sparsi_ebp)

        return num/den

    def getIRFfeat(self, windows):
        """Extract Irregularity Factor (IRF) feature."""
        def closure(w):
            m0 = np.sqrt(np.sum(w**2,axis=2))/(w.shape[2]-1)
            m0 = m0 ** 0.1 / 0.1
            d1 = np.diff(w, n=1, axis=2)
            m2 = np.sqrt(np.sum(d1 **2, axis=2)/ (w.shape[2]-1))
            m2 = m2 ** 0.1 / 0.1
            d2 = np.diff(d1, n=1, axis=2)
            m4 = np.sqrt(np.sum(d2 **2, axis=2)/ (w.shape[2]-1))
            m4 = m4 ** 0.1 / 0.1
            irf = m2/np.sqrt(m0*m4)
            return np.log(np.abs(irf))
        irf_ebp=closure(windows)
        irf_efp=closure(np.log(windows**2+np.spacing(1)))

        num=-2*np.multiply(irf_efp,irf_ebp)
        den=np.multiply(irf_efp, irf_efp) + np.multiply(irf_ebp, irf_ebp)

        return num/den

    def getWLFfeat(self, windows):
        """Waveform Length Factor (WLF) feature."""
        def closure(w):
            d1 = np.diff(w, n=1, axis=2)

            d2 = np.diff(d1, n=1, axis=2)

            wlf = np.sqrt(np.sum(np.abs(d1),axis=2)/np.sum(np.abs(d2),axis=2))
            return np.log(np.abs(wlf))
        wlf_ebp=closure(windows)
        wlf_efp=closure(np.log(windows**2+np.spacing(1)))

        num=-2*np.multiply(wlf_efp,wlf_ebp)
        den=np.multiply(wlf_efp, wlf_efp) + np.multiply(wlf_ebp, wlf_ebp)

        return num/den

    def getLDfeat(self, windows):
        """Extract Log Detector (LD) feature."""
        return np.exp(np.mean(np.log(np.abs(windows)+1), 2))

    def getMAVFDfeat(self, windows):
        """Extract Mean Absolute Value First Difference (MAVFD) feature."""
        mavfd = np.mean(np.abs(np.diff(windows,axis=2)),axis=2)
        return mavfd

    def getMDFfeat(self, windows,MDF_fs=1000):
        """Extract Median Frequency (MDF) feature.

        Parameters
        ----------
        windows: list
            A list of windows.
        MDF_fs: int, float
            The sampling frequency of the signal
        """
        assert type(MDF_fs) == int or type(MDF_fs) == float
        def closure(winsize):
            return 1 if winsize==0 else 2**math.ceil(math.log2(winsize))
        nextpow2 = closure(windows.shape[2])
        spec = np.fft.fft(windows,nextpow2, axis=2)/windows.shape[2]
        spec = spec[:,:,0:int(nextpow2/2)]
        POW = np.real(spec * np.conj(spec))
        totalPOW = np.sum(POW, axis=2)
        cumPOW   = np.cumsum(POW, axis=2)
        medfreq = np.zeros((windows.shape[0], windows.shape[1]))
        for i in range(0, windows.shape[0]):
            for j in range(0, windows.shape[1]):
                medfreq[i,j] = (MDF_fs/2)*np.argwhere(cumPOW[i,j,:] > totalPOW[i,j] /2)[0]/(nextpow2/2)
        return medfreq

    def getMNFfeat(self, windows, MNF_fs=1000):
        """Extract Mean Frequency (MNF) feature.

        Parameters
        ----------
        windows: list
            A list of windows.
        MNF_fs: int, float
            The sampling frequency of the signal
        """
        assert type(MNF_fs) == int or type(MNF_fs) == float
        def closure(winsize):
            return 1 if winsize==0 else 2**math.ceil(math.log2(winsize))
        nextpow2 = closure(windows.shape[2])
        spec = np.fft.fft(windows, n=nextpow2,axis=2)/windows.shape[2]
        f = np.fft.fftfreq(nextpow2)*MNF_fs
        spec = spec[:,:,0:int(round(spec.shape[2]/2))]
        f = f[0:int(round(nextpow2/2))]
        f = np.repeat(f[np.newaxis, :], spec.shape[0], axis=0)
        f = np.repeat(f[:, np.newaxis,:], spec.shape[1], axis=1)
        POW = spec * np.conj(spec)
        return np.real(np.sum(POW*f,axis=2)/np.sum(POW,axis=2))

    def getMNPfeat(self, windows):
        """Extract Mean Power (MNP) feature."""
        def closure(winsize):
            return 1 if winsize==0 else 2**math.ceil(math.log2(winsize))
        nextpow2 = closure(windows.shape[2])
        spec = np.fft.fft(windows,n=nextpow2,axis=2)/windows.shape[2]
        spec = spec[:,:,0:int(round(nextpow2/2))]
        POW  = np.real(spec[:,:,:int(nextpow2)]*np.conj(spec[:,:,:int(nextpow2)]))
        return np.sum(POW, axis=2)/POW.shape[2]

    def getMPKfeat(self, windows):
        """Extract Peak (MPK) feature."""
        return windows.max(axis=2)

    def getSKEWfeat(self, windows):
        """Extract Skewness (SKEW) feature."""
        return skew(windows, axis=2)

    def getKURTfeat(self, windows):
        """Extract Kurtosis (KURT) feature."""
        return kurtosis(windows, axis=2, fisher=False)

    def getPAPfeat(self, windows):
        """Extract Peak Average Power (PaP) feature."""
        d1 = np.diff(windows, axis=2)
        d2 = np.diff(d1, axis=2)
        m0 = np.sqrt(np.sum(windows**2,axis=2))
        m2 = np.sqrt(np.sum(d1**2, axis=2))
        m4 = np.sqrt(np.sum(d2**2, axis=2))
        return  m0 / (m4/m2)

    def getMZPfeat(self, windows):
        """Extract Multiplication of Power and Peaks (MZP) feature."""
        d1 = np.diff(windows, axis=2)
        phi = np.sqrt(1/windows.shape[2] * np.sum(d1 ** 2, axis=2))
        return phi

    def getTMfeat(self, windows, TM_order=3):
        """Extract Temporal Moment (TM) feature.

        Parameters
        ----------
        windows: list
            A list of windows.
        TM_order: int, default=3
            The exponent the time series is raised to before the MAV is computed.
        """
        assert type(TM_order)==int
        return np.mean(np.abs(windows**TM_order), axis=2)

    def getSMfeat(self, windows, SM_order=2, SM_fs=1000):
        """Extract Spectral Moment (SM) feature.

        Parameters
        ----------
        windows: list
            A list of windows.
        SM_order: int, default=2
            The exponent that the frequency domain is raised to.
        SM_fs: float, default=1000
            The sampling frequency (in Hz).
        """
        assert type(SM_order)==int
        assert type(SM_fs)==int or type(SM_fs) == float
        def closure(winsize):
            return 1 if winsize==0 else 2**math.ceil(math.log2(winsize))
        nextpow2 = closure(windows.shape[2])
        spec = np.fft.fft(windows,n=nextpow2,axis=2)/windows.shape[2]
        pow  =  np.real(spec[:,:,0:int(round(nextpow2/2))] * np.conj(spec[:,:,0:int(round(nextpow2/2))]))
        f = np.fft.fftfreq(nextpow2)*SM_fs
        f = f[0:int(round(nextpow2/2))]
        f = np.repeat(f[np.newaxis, :], spec.shape[0], axis=0)
        f = np.repeat(f[:, np.newaxis,:], spec.shape[1], axis=1)
        return np.sum( pow*(f**SM_order),axis=2)

    def getSAMPENfeat(self, windows, SAMPEN_dim=2, SAMPEN_tolerance=0.3):
        """Extract Sample Entropy (SAMPEN) feature. SAMPEN_dim should be specified and is the number of samples that
        are used to define patterns. SAMPEN_tolerance depends on the dataset and is the minimum distance between patterns
        to be considered the same pattern; we recommend a value near 0.3.

        Parameters
        ----------
        windows: list
            A list of windows.
        SAMPEN_dim: int, default=2
            The number of samples patterns are defined under.
        SAMPEN_tolerance: float, default=0.3
            The threshold for patterns to be considered similar
        """
        assert type(SAMPEN_dim) == int
        assert SAMPEN_dim > 1
        assert type(SAMPEN_tolerance) == float
        assert SAMPEN_tolerance > 0
        #standardize within window
        N = windows.shape[2]
        window_mean = np.mean(windows,axis=2)
        window_std = np.std(windows, axis=2)
        series = (windows - np.repeat(window_mean[:,:,None], N, axis=2))/np.repeat(window_std[:,:,None], N, axis=2)
        # get sampen feature variable ready
        sampen = np.zeros((windows.shape[0], windows.shape[1]))
        # We don't have an efficient implementation (doing all channels/windows with matrix multiplication)
        # so do it one window at a time
        for w  in range(windows.shape[0]):
            for ch in range(windows.shape[1]):
                results = []
                for j in [1,2]:
                    m = SAMPEN_dim + j - 1
                    patterns = np.zeros((m,N-m+1))
                    count = np.zeros((N-m))
                    # if 1 d embedding
                    if m == 1:
                        patterns = series[w,ch,:]
                    else:
                        for k in range(0,m):
                            patterns[k,:] = series[w,ch, k:N-m+k+1]

                    # Count the number of patterns whose distance is less than the tolerance
                    for k in range(N-m):
                        # compute the distance between each pattern and other patterns
                        if m == 1:
                            tmp = np.abs(patterns - matlib.repmat(patterns[:,k],1,N-m+1))
                        else:
                            tmp = np.max(np.abs(patterns - matlib.repmat(patterns[:,k,np.newaxis],1,N-m+1)),axis=0)
                        mask = (tmp <= SAMPEN_tolerance)
                        count[k] = (np.sum(mask)-1) # we remove 1 to avoid self comparison, in theory this means we can eventually do log of 0 (error)
                        # that is why we need the eps / np.spacing(1)
                    # average the number of similar patterns
                    count = count / (N-SAMPEN_dim-1)
                    results.append(np.mean(count))
                sampen[w,ch] = np.log((results[0]+np.spacing(1))/(results[1]+np.spacing(1)))
        return sampen

    def getFUZZYENfeat(self, windows, FUZZYEN_dim=2, FUZZYEN_tolerance=0.3, FUZZYEN_win=2):
        """Extract Fuzzy Entropy (FUZZYEN) feature. Similar to SAMPEN but uses fuzzy membership
        functions instead of hard thresholds.

        Parameters
        ----------
        windows: list
            A list of windows.
        FUZZYEN_dim: int, default=2
            The number of samples patterns are defined under.
        FUZZYEN_tolerance: float, default=0.3
            The threshold for patterns to be considered similar
        FUZZYEN_win: int, default=2
            the order the distance matrix is raised to prior to determining the similarity.
        """
        assert type(FUZZYEN_dim) == int
        assert FUZZYEN_dim > 1
        assert type(FUZZYEN_tolerance) == float
        assert FUZZYEN_tolerance > 0
        assert type(FUZZYEN_win) == int
        assert FUZZYEN_win > 0

        #standardize within window
        FUZZYEN_tolerance = FUZZYEN_tolerance*np.std(windows,axis=2)
        N = windows.shape[2]
        fuzzyen = np.zeros((windows.shape[0], windows.shape[1]))
        for w  in range(windows.shape[0]):
            for ch in range(windows.shape[1]):
                results = []
                for j in [1,2]:
                    m = FUZZYEN_dim + j - 1
                    dataMat = np.zeros((m,N-m+1))
                    phi = np.zeros((N-m+1))
                    if m == 1:
                        dataMat[m,:] = windows[w,ch,:]
                    else:
                        for k in range(0,m):
                            dataMat[k,:] = windows[w,ch, k:N-m+k+1]

                    for k in range(N-m+1):
                        dataMat[:,k] = dataMat[:,k]-np.mean(dataMat[:,k])

                    for k in range(N-m):
                        if m == 1:
                            tmp = np.abs(dataMat - matlib.repmat(dataMat[:,k],1,N-m+1))
                        else:
                            tmp = np.max(np.abs(dataMat - matlib.repmat(dataMat[:,k,np.newaxis],1,N-m+1)),axis=0)
                        simi = np.exp(((-1)*((tmp)**FUZZYEN_win))/FUZZYEN_tolerance[w,ch])
                        phi[k]=(np.sum(simi)-1) / (windows.shape[2]-m-1)

                    results.append(np.sum(phi)/(N-m))
                fuzzyen[w,ch] = np.log((results[0]+np.spacing(1))/(results[1]+np.spacing(1)))
        return fuzzyen

    def getISDfeat(self, windows):
        """Extract Integral Square Descriptor (ISD) feature."""
        return np.sum(windows**2, axis=2)

    def getCORfeat(self, windows):
        """Extract Coefficient of Regularization (COR) feature."""
        ISD = np.sum(windows**2, axis=2)
        normRSd1 = np.sum(np.diff(windows,axis=2)**2,axis=2)/windows.shape[2]
        normRSd2 = np.sum(np.diff(np.diff(windows, axis=2),axis=2)**2,axis=2)/windows.shape[2]
        COR = normRSd1/(normRSd2*ISD)
        return COR

    def getMDIFFfeat(self, windows):
        """Extract Mean Difference Derivative (MDIFF) feature."""
        return np.sum(np.diff(windows,axis=2)**2,axis=2)/windows.shape[2]

    def getMLKfeat(self, windows):
        """Extract Mean Logarithm Kernel (MLK) feature."""
        return np.log(np.sum(np.abs(windows),axis=2)+np.spacing(1))/windows.shape[2]

    def getACTfeat(self, windows):
        """Extract Activation (ACT) feature. This feature is very similar to the zeroth order moment feature of TDPSD (M0); however, it undergoes
        no nonlinear normalization."""
        return np.mean(windows**2,axis=2)

    def getMOBfeat(self, windows):
        """Extract Mobility (MOB) feature. This feature is sqrt(m2/m0), where m0 and m2 are the first and second order moments found via
        Parseval's theorem."""
        m0 =  self.getACTfeat(windows)
        m2 =  np.sum(np.diff(windows,axis=2)**2,axis=2)/windows.shape[2]
        return np.sqrt(m2/m0)

    def getCOMPfeat(self, windows):
        """Extract Complexity (COMP) feature. This feature is sqrt(m4/m2), where m2 and m4 are the second and fourth order moments found via
        Parseval's theorem. It is a measure of the the similarity of the shape of a signal compared to a pure sine waveform."""
        m2 =  np.sum(np.diff(windows,axis=2)**2,axis=2)/windows.shape[2]
        m4 =  np.sum(np.diff(np.diff(windows, axis=2),axis=2)**2)/windows.shape[2]
        return np.sqrt(m4/m2)

    def _format_data(self, feature_dictionary):
        if not isinstance(feature_dictionary, dict):
            return feature_dictionary
        arr = None
        for feat in feature_dictionary:
            if arr is None:
                arr = feature_dictionary[feat]
            else:
                arr = np.hstack((arr, feature_dictionary[feat]))
        return arr
