package swift;


public class StpChecker {

    public static void check(Mt103Message msg) {
        boolean hasStp = BlockParser.block3HasSubTag(msg.block3, "119", "STP");

        if (!hasStp) {
            msg.stpCompliant = false;
            return;
        }

        boolean violations = false;

        // Constraint 2: Ordering customer must use :50A: or :50F: (not :50K:)
        if (msg.hasField("50K")) {
            msg.addError(":50K:", "STP_VIOLATION", "STP requires :50A: or :50F:, not :50K:");
            violations = true;
        }

        // Constraint 3: All institution fields must use option A only
        String[] institutionFields = {"52", "53", "54", "55", "56", "57"};
        for (String base : institutionFields) {
            // Check if B, C, or D options are used
            for (String suffix : new String[]{"B", "C", "D"}) {
                if (msg.hasField(base + suffix)) {
                    msg.addError(":" + base + suffix + ":", "STP_VIOLATION",
                        "STP requires option A for institution field :" + base + "a:");
                    violations = true;
                }
            }
        }

        // Constraint 4: Beneficiary format - :59:, :59A:, :59F: are all allowed
        // (no restriction beyond what's normally valid)

        msg.stpCompliant = !violations;
    }
}
