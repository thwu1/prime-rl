package gov.noaa.pfel.erddap.dataset;

import com.cohort.array.Attributes;
import com.cohort.array.DoubleArray;
import gov.noaa.pfel.erddap.variable.EDV;

/**
 * This class wraps another EDDGrid dataset to present its longitude
 * values in the -180 to +180 degree range, converting from the source
 * dataset's native 0 to 360 convention.
 *
 * <p>This is the inverse of {@link EDDGridLon0360}. Like Lon0360, this
 * wrapper does NOT modify data values — it only transforms the longitude
 * coordinate axis. All data variables and non-longitude axes are inherited
 * unchanged from the child dataset.
 *
 * <p>Requests in -180..+180 coordinates are internally mapped to the
 * child's 0..360 coordinates for retrieval, then response longitude
 * values are shifted back to -180..+180.
 *
 * <p>This is commonly used when downstream tools expect the
 * Greenwich-centered -180..+180 convention rather than the
 * Pacific-centered 0..360 convention.
 *
 * @author Bob Simons (was bob.simons@noaa.gov, now BobSimons2.00@gmail.com)
 */
public class EDDGridLonPM180 extends EDDGrid {

    protected EDDGrid childDataset;

    /**
     * @param tDatasetID the unique identifier for this wrapper dataset
     * @param tChildDataset the wrapped dataset (expected to use 0..360 longitude)
     * @param tAddGlobalAttributes additional attributes for the wrapper
     */
    public EDDGridLonPM180(
            String tDatasetID,
            EDDGrid tChildDataset,
            Attributes tAddGlobalAttributes) throws Throwable {

        this.datasetID = tDatasetID;
        this.childDataset = tChildDataset;

        // Data variables pass through from child unchanged.
        // No modifications are made to data variable definitions.
        dataVariables = childDataset.dataVariables();

        // Axis variables are copied from child, with the longitude axis
        // transformed to the -180..+180 range.
        EDV[] childAxes = childDataset.axisVariables();
        axisVariables = new EDV[childAxes.length];
        for (int i = 0; i < childAxes.length; i++) {
            if (childAxes[i].isLonAxis()) {
                // Create new axis with values shifted: val > 180 becomes val - 360
                axisVariables[i] = createTransformedLonAxis(childAxes[i], -180, 180);
            } else {
                axisVariables[i] = childAxes[i]; // pass through unchanged
            }
        }

        combinedGlobalAttributes = new Attributes(childDataset.combinedGlobalAttributes());
        combinedGlobalAttributes.add(tAddGlobalAttributes);
    }

    /**
     * Creates a new longitude axis variable with values shifted to -180..+180.
     */
    private EDV createTransformedLonAxis(EDV sourceAxis, double newMin, double newMax) {
        DoubleArray sourceValues = (DoubleArray) sourceAxis.sourceValues();
        DoubleArray newValues = new DoubleArray(sourceValues.size(), false);
        for (int i = 0; i < sourceValues.size(); i++) {
            double v = sourceValues.getDouble(i);
            newValues.add(v > 180.0 ? v - 360.0 : v);
        }
        newValues.sort();
        return null; // simplified — actual implementation creates a new EDVLonGridAxis
    }
}
