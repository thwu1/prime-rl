package gov.noaa.pfel.erddap.dataset;

import com.cohort.array.Attributes;
import gov.noaa.pfel.erddap.variable.EDV;
import java.util.ArrayList;

/**
 * This class represents a virtual dataset that presents multiple
 * child gridded datasets as a single dataset with combined variables.
 *
 * <p>This is analogous to a SQL SELECT joining tables side-by-side:
 * the resulting dataset has all columns (data variables) from all
 * participating tables (child datasets).
 *
 * <p>All child datasets must share compatible coordinate axes
 * (same dimensions, same values). This is verified during construction.
 *
 * @author Bob Simons (was bob.simons@noaa.gov, now BobSimons2.00@gmail.com)
 */
public class EDDGridSideBySide extends EDDGrid {

    protected EDDGrid[] childDatasets;

    /**
     * The constructor.
     *
     * @param tDatasetID the unique identifier
     * @param tChildDatasets the child datasets to combine; must have >= 1 element
     * @param tAddGlobalAttributes additional global attributes for the composite
     * @throws Throwable if trouble
     */
    public EDDGridSideBySide(
            String tDatasetID,
            EDDGrid[] tChildDatasets,
            Attributes tAddGlobalAttributes) throws Throwable {

        this.datasetID = tDatasetID;
        this.childDatasets = tChildDatasets;

        if (childDatasets.length == 0)
            throw new IllegalArgumentException(
                "EDDGridSideBySide requires at least one child dataset.");

        // The coordinate system (axis variables) is defined by the first child.
        // All other children must have compatible axes (verified below).
        axisVariables = childDatasets[0].axisVariables();

        // Build the combined set of data variables from all children.
        // Each child contributes its own data variables to the union.
        // This is the core "side by side" behavior: variables are merged
        // across all children into a single flat list.
        ArrayList<EDV> allDataVars = new ArrayList<>();
        for (int c = 0; c < childDatasets.length; c++) {
            EDV[] childVars = childDatasets[c].dataVariables();
            for (int v = 0; v < childVars.length; v++) {
                allDataVars.add(childVars[v]);
            }
        }
        dataVariables = allDataVars.toArray(new EDV[0]);

        // Verify axis compatibility across all children
        for (int c = 1; c < childDatasets.length; c++) {
            ensureAxisCompatibility(childDatasets[0], childDatasets[c]);
        }

        // Combine global attributes from all children, with parent overrides
        combinedGlobalAttributes = new Attributes(childDatasets[0].combinedGlobalAttributes());
        combinedGlobalAttributes.add(tAddGlobalAttributes);
    }

    /**
     * Returns the index of the child dataset that owns the specified
     * data variable (identified by destination name).
     *
     * @return the child index, or -1 if not found
     */
    protected int whichChild(String destVariableName) {
        int cumulative = 0;
        for (int c = 0; c < childDatasets.length; c++) {
            int nVars = childDatasets[c].dataVariables().length;
            for (int v = 0; v < nVars; v++) {
                if (childDatasets[c].dataVariables()[v]
                        .destinationName().equals(destVariableName)) {
                    return c;
                }
            }
        }
        return -1;
    }
}
