package gov.noaa.pfel.erddap.dataset;

import com.cohort.array.Attributes;
import com.cohort.array.DoubleArray;
import gov.noaa.pfel.erddap.variable.EDV;

/**
 * This class wraps another EDDGrid dataset to present its longitude
 * values in the 0 to 360 degree range, converting from the source
 * dataset's native -180 to 180 convention.
 *
 * <p>This wrapper does NOT modify the underlying data values — it only
 * transforms the longitude coordinate axis. Data variable definitions
 * and all non-longitude axes pass through unchanged from the wrapped
 * child dataset.
 *
 * <p>Requests are translated: user requests in 0..360 coordinates are
 * internally mapped to the child's -180..180 coordinates for data retrieval,
 * then the response longitude values are shifted back to 0..360.
 *
 * <p>This is commonly used when downstream tools or users expect longitude
 * in the Pacific-centered 0..360 convention rather than the
 * Greenwich-centered -180..180 convention.
 *
 * @author Bob Simons (was bob.simons@noaa.gov, now BobSimons2.00@gmail.com)
 */
public class EDDGridLon0360 extends EDDGrid {

    protected EDDGrid childDataset;

    /**
     * @param tDatasetID the unique identifier for this wrapper dataset
     * @param tChildDataset the wrapped dataset (expected to use -180..180 longitude)
     * @param tAddGlobalAttributes additional attributes for the wrapper
     */
    public EDDGridLon0360(
            String tDatasetID,
            EDDGrid tChildDataset,
            Attributes tAddGlobalAttributes) throws Throwable {

        this.datasetID = tDatasetID;
        this.childDataset = tChildDataset;

        // Data variables are inherited directly from the child — no changes.
        // The wrapper does not add, remove, or modify any data variables.
        dataVariables = childDataset.dataVariables();

        // Axis variables are copied from child, but the longitude axis
        // is transformed to use 0..360 range values.
        EDV[] childAxes = childDataset.axisVariables();
        axisVariables = new EDV[childAxes.length];
        for (int i = 0; i < childAxes.length; i++) {
            if (childAxes[i].isLonAxis()) {
                // Create new axis with values shifted: val < 0 becomes val + 360
                axisVariables[i] = createTransformedLonAxis(childAxes[i], 0, 360);
            } else {
                axisVariables[i] = childAxes[i]; // pass through unchanged
            }
        }

        combinedGlobalAttributes = new Attributes(childDataset.combinedGlobalAttributes());
        combinedGlobalAttributes.add(tAddGlobalAttributes);
    }

    /**
     * Creates a new longitude axis variable with values shifted to 0..360.
     */
    private EDV createTransformedLonAxis(EDV sourceAxis, double newMin, double newMax) {
        DoubleArray sourceValues = (DoubleArray) sourceAxis.sourceValues();
        DoubleArray newValues = new DoubleArray(sourceValues.size(), false);
        for (int i = 0; i < sourceValues.size(); i++) {
            double v = sourceValues.getDouble(i);
            newValues.add(v < 0 ? v + 360.0 : v);
        }
        newValues.sort();
        // Return new EDV with transformed values and updated metadata
        return null; // simplified — actual implementation creates a new EDVLonGridAxis
    }
}
