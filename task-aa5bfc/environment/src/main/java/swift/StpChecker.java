package swift;


/**
 * Checks whether an MT103 message is STP (Straight-Through Processing) compliant.
 *
 * STP compliance requires:
 * 1. Block 3 contains {119:STP}
 * 2. Ordering customer uses :50A: or :50F: (not :50K:)
 * 3. All institution fields use option A (BIC only)
 * 4. Beneficiary uses :59:, :59A:, or :59F:
 *
 * BUG: Only checks for {119:STP} tag, doesn't validate constraints 2-4
 * BUG: Even the STP tag detection is broken
 */
public class StpChecker {

    public static void check(Mt103Message msg) {
        // Check if {119:STP} is present in block 3
        // BUG: using wrong method - block3HasSubTag has its own bugs
        boolean hasStp = BlockParser.block3HasSubTag(msg.block3, "119", "STP");

        if (!hasStp) {
            msg.stpCompliant = false;
            return;
        }

        // BUG: Should validate constraints 2-4 and report STP_VIOLATION errors
        // Currently just sets stpCompliant = true without checking anything
        msg.stpCompliant = true;

        // TODO: Check constraint 2 - :50A: or :50F: only (not :50K:)
        // TODO: Check constraint 3 - institution fields must use option A only
        // TODO: Check constraint 4 - beneficiary format check
    }
}
