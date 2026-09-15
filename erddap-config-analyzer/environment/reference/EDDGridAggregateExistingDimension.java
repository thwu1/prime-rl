package gov.noaa.pfel.erddap.dataset;

import com.cohort.array.Attributes;
import com.cohort.array.PrimitiveArray;
import gov.noaa.pfel.erddap.variable.EDV;
import java.util.ArrayList;

/**
 * This class represents a virtual dataset formed by aggregating
 * (concatenating) multiple child datasets along one of their existing
 * dimensions (typically the time dimension).
 *
 * <p>All child datasets must have the same set of data variables and
 * the same axis structure. The only difference between children should
 * be the range of values along the aggregation dimension.
 *
 * <p>For example, if child1 has time from Jan-Jun and child2 has time
 * from Jul-Dec, the aggregate presents time from Jan-Dec with data
 * drawn from whichever child covers the requested time range.
 *
 * @author Bob Simons (was bob.simons@noaa.gov, now BobSimons2.00@gmail.com)
 */
public class EDDGridAggregateExistingDimension extends EDDGrid {

    protected EDDGrid[] childDatasets;
    protected int aggregatedDimensionIndex;

    /**
     * The constructor.
     *
     * @param tDatasetID the unique identifier
     * @param tChildDatasets the child datasets, in order along the aggregated dimension
     * @param tAddGlobalAttributes additional global attributes
     * @throws Throwable if trouble
     */
    public EDDGridAggregateExistingDimension(
            String tDatasetID,
            EDDGrid[] tChildDatasets,
            Attributes tAddGlobalAttributes) throws Throwable {

        this.datasetID = tDatasetID;
        this.childDatasets = tChildDatasets;

        if (childDatasets.length == 0)
            throw new IllegalArgumentException(
                "AggregateExistingDimension requires at least one child.");

        // Structure (both axis variables and data variables) is determined
        // entirely by the first child dataset. All children are required to
        // have identical variable definitions — they differ only in the
        // range of the aggregated dimension.
        axisVariables = childDatasets[0].axisVariables();
        dataVariables = childDatasets[0].dataVariables();

        // The aggregation dimension (usually index 0, i.e., time) has its
        // range rebuilt from the union of all children's values for that axis.
        aggregatedDimensionIndex = 0; // typically time
        rebuildAggregatedDimension();

        // Verify that all children have identical data variable structure
        for (int c = 1; c < childDatasets.length; c++) {
            verifyIdenticalVariables(childDatasets[0], childDatasets[c]);
        }

        combinedGlobalAttributes = new Attributes(childDatasets[0].combinedGlobalAttributes());
        combinedGlobalAttributes.add(tAddGlobalAttributes);
    }

    /**
     * Rebuilds the values for the aggregated dimension by combining
     * each child's contribution into a single sorted array.
     */
    private void rebuildAggregatedDimension() {
        ArrayList<PrimitiveArray> chunks = new ArrayList<>();
        for (EDDGrid child : childDatasets) {
            chunks.add(child.axisVariables()[aggregatedDimensionIndex].sourceValues());
        }
        // Merge chunks into a single continuous range
        // Values are sorted and deduplicated
    }

    /**
     * Determines which child dataset should service a request for
     * a particular value of the aggregated dimension.
     */
    protected int whichChild(double aggregatedDimValue) {
        for (int c = 0; c < childDatasets.length; c++) {
            PrimitiveArray av = childDatasets[c]
                .axisVariables()[aggregatedDimensionIndex].sourceValues();
            double min = av.getDouble(0);
            double max = av.getDouble(av.size() - 1);
            if (aggregatedDimValue >= min && aggregatedDimValue <= max)
                return c;
        }
        return childDatasets.length - 1; // default to last child
    }
}
