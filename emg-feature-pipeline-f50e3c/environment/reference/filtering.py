import scipy.signal
import numpy as np
import math

class Filter:
    """ A class that will perform filtering on data in numpy.ndarrays.

    Parameters
    ----------
    sampling_frequency: int
        The sampling frequency of the device used. This must be known for the
        digital filters to do what is intended.
    """
    def __init__(self, sampling_frequency):
        self.sampling_frequency = sampling_frequency

    def install_filters(self, filter_dictionary={}):
        '''Install a particular filter.

        Installing filters is required prior to filtering being performed. Filters are created using the scipy.signal package.
        The necessary parameters for these filters are included in a dictionary. When multiple filters are intended to be used
        at a time, install them sequentially by calling this function for each filter. If there is a specific order for the filters
        then install them in the intended processing order.

        Parameters
        ----------
        filter_dictionary: dict
            A dictionary containing the necessary parameters for defining a single filter.

        Examples
        -------
        >>> # create a notch filter for removing power line interference
        >>> filter_dictionary={ "name": "notch", "cutoff": 60, "bandwidth": 3}
        >>> # create a filter for removing high frequency noise and low frequency motion artefacts
        >>> filter_dictionary={ "name":"bandpass", "cutoff": [20, 450], "order": 4}
        >>> # create a filter for low frequency motion artefacts
        >>> filter_dictionary={ "name": "highpass", "cutoff": 20, "order":2}
        '''
        installed_filter = {"name":filter_dictionary["name"]}
        if filter_dictionary["name"] == "notch":
            assert filter_dictionary["cutoff"]/(self.sampling_frequency/2) < 1 # cutoff given too high for nyquist rate
            installed_filter["b"], installed_filter["a"] = scipy.signal.iirnotch(w0=filter_dictionary["cutoff"],
                                                                                 Q=filter_dictionary["cutoff"]/filter_dictionary["bandwidth"],
                                                                                 fs=self.sampling_frequency)
        elif filter_dictionary["name"] in ["lowpass","highpass","bandpass","bandstop"]:
            # normalize cutoff by nyquist rate (sampling frequency/2)
            if type(filter_dictionary["cutoff"])==list:
                cutoff = [i/(self.sampling_frequency/2) for i in filter_dictionary["cutoff"]]
                assert sum([i > 1 for i in cutoff]) == 0 # cutoff given too high for nyquist rate
            else:
                cutoff = filter_dictionary["cutoff"]/(self.sampling_frequency/2)
                assert cutoff < 1 # cutoff given too high for nyquist rate

            installed_filter["b"], installed_filter["a"] = scipy.signal.butter(N=filter_dictionary["order"],
                                                                               Wn=cutoff,
                                                                               btype=filter_dictionary["name"])

        if hasattr(self, "filters"):
            setattr(self, "filters", getattr(self, "filters")+[(installed_filter)])
        else:
            setattr(self, "filters", [installed_filter])

    def install_common_filters(self):
        '''Install a set of common filters to minimize motion artefact and power line interference in North America. This will install a
        bandpass filter from 20Hz-450Hz and a notch filter at 60Hz.
        '''
        if self.sampling_frequency < 1000:
            print("sampling frequency is inadequate for the set of common filters.")
            filter_dictionary={"name":"highpass",
                               "cutoff": 20,
                               "order": 2}
        else:
            filter_dictionary={"name":"bandpass",
                            "cutoff": [20, 450],
                            "order": 4 }

        self.install_filters(filter_dictionary=filter_dictionary)
        filter_dictionary={"name":"notch",
                            "cutoff": 60,
                            "bandwidth": 3 }
        self.install_filters(filter_dictionary=filter_dictionary)

    def filter(self, data):
        ''' Run installed filters on data.

        Parameters
        ----------
        data: np.ndarray
            The data that will be passed through the filters.

        Returns
        -------
        np.ndarray
            Returns the filtered data.
        '''
        if not hasattr(self, "filters"):
            print("No filters have been installed")
            return data

        if type(data) == np.ndarray:
            return self._filter_np_ndarray(data)
        else:
            print("An unsupported data type was passed into the function")

    def _filter_np_ndarray(self, data):
        ''' Helper function that runs the installed filters on an np.ndarray.

        Parameters
        ----------
        data: np.ndarray
            The data that will be passed through the filters.

        Returns
        -------
        np.ndarray
            Data that has been filtered.
        '''
        return self._run_filter(data)

    def _run_filter(self, matrix):
        ''' Helper function that actually runs the installed filters on an np.ndarray.

        Parameters
        ----------
        matrix: np.ndarray
            The data that will be passed through the filters.

        Returns
        -------
        matrix: np.ndarray
            Data that has been filtered.
        '''
        for fl in range(len(self.filters)):
            if self.filters[fl]["name"] in ["lowpass","highpass","bandpass","bandstop","notch"]:
                matrix = scipy.signal.filtfilt(self.filters[fl]["b"],
                                            self.filters[fl]["a"],
                                            matrix,
                                            axis=0)
        return matrix
