A RAVEN-style analysis environment contains noisy state-space observations from a discrete-time linear dynamical system stored in HDF5 format at `/app/data/system_observations.h5`. An XML output specification at `/app/config/output_spec.xml` defines the required result structure and dual-format output.

Analyze the observed system to produce four results:

1. **Intrinsic dimensionality**: Determine how many independent dynamic modes the system truly has, despite observation noise corrupting all measurements.
2. **Dynamic modes**: Extract the system's dominant discrete-time modes, including any oscillatory (complex-valued) behavior. Report them as eigenvalues.
3. **Forecast**: Predict the system's state beyond the observation window for the number of future steps specified in the HDF5 metadata.
4. **Reconstruction quality**: Quantify how well your identified model reproduces the original noisy observations (RMSE).

Inspect the HDF5 input file to understand the data layout (groups, datasets, attributes). Parse the XML specification to understand the required output field names, data types, sorting, and the HDF5 group hierarchy for the output file.

Write results to **both** `/app/results.json` and `/app/results.h5` following the structure defined in the XML specification. The HDF5 output must use the group paths specified in the XML `GroupMapping` elements.