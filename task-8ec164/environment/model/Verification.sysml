/* Selene Verification Relationships
 * Maps requirements to satisfying system elements,
 * defines verification case structures, and establishes
 * requirement derivation chains.
 *
 *
 * Satisfaction semantics: A "satisfy" relationship maps a
 * requirement to the system element responsible for meeting it.
 * The satisfy target path uses dot notation through the part
 * hierarchy (e.g., seleneSystem.transferVehicle.tvPropulsion).
 * The LAST segment of the path identifies the component name
 * for traceability reporting.
 *
 * Derivation semantics: A "derive" relationship within a
 * requirement specialization block indicates that the child
 * requirement was derived from the parent requirement. The
 * child req name is the name of the specializing requirement;
 * the parent is the derived-from requirement.
 */

package SeleneVerification {

    import SeleneArchitecture::seleneSystem;
    import SeleneRequirements::*;

    /* ---- Requirement satisfaction links ---- */

    /* NOTE: systemMassReq (REQ-SYS-001) intentionally has NO satisfy
       link. This is a DELIBERATE traceability gap: no specific
       component is allocated sole responsibility for the overall
       system mass budget. The system mass is an emergent property
       of the full architecture. A verification engine must detect
       and flag this gap in the traceability report.

       All other requirements have explicit satisfy links to the
       component responsible for meeting them. */

    satisfy tvDryMassReq by seleneSystem.transferVehicle;

    satisfy lnDryMassReq by seleneSystem.lander;

    satisfy tvDeltaVReq by seleneSystem.transferVehicle.tvPropulsion;

    satisfy lnDeltaVReq by seleneSystem.lander.lnPropulsion;

    satisfy tvPowerReq by seleneSystem.transferVehicle.tvPower;

    satisfy lnPowerReq by seleneSystem.lander.lnPower;

    satisfy payloadReq by seleneSystem.lander.lnPayload;

    /* ---- Requirement derivation chains ---- */

    /* Derivation captures that subsystem mass budgets are
       allocated from the top-level system mass budget. This
       forms a two-level derivation tree:
         systemMassReq
           ├── tvMassDerived (TV dry mass budget)
           └── lnMassDerived (LN dry mass budget)
    */

    requirement tvMassDerived :> tvDryMassReq {
        doc /* Transfer vehicle mass budget derives from
               the overall system mass budget. The TV dry mass
               limit was set to maintain adequate propellant
               mass fraction given the system mass constraint. */
        derive requirement systemMassReq;
    }

    requirement lnMassDerived :> lnDryMassReq {
        doc /* Lander mass budget derives from the overall
               system mass budget. The lander dry mass limit
               ensures sufficient propellant fraction for the
               descent delta-v requirement. */
        derive requirement systemMassReq;
    }

    /* ---- Verification case definitions ---- */

    verification def MassVerification {
        doc /* Verifies mass requirements by computing recursive
               mass rollup from the system architecture model and
               comparing computed values against requirement
               threshold limits.

               Procedure:
               1. Parse part hierarchy from Architecture.sysml
               2. Compute leaf-to-root mass rollup
               3. Identify consumable parts (isConsumable = true)
               4. Compute dry mass = total - consumable
               5. Compare against REQ-SYS-001, REQ-TV-001, REQ-LN-001
               6. Report PASS/FAIL with actual vs limit values */

        subject systemUnderTest : SpacecraftDefinitions::LunarCargoDeliverySystem;

        objective massObjective {
            doc /* Verify that all mass-related requirements
                   are satisfied by the current architecture.
                   Expected: REQ-SYS-001 FAILS (system over mass),
                   REQ-TV-001 and REQ-LN-001 PASS. */
        }

        action collectMassData {
            doc /* Extract mass attributes from the model
                   part hierarchy for all leaf components.
                   Ignore designMass and allocatedMass. */
        }

        action computeRollup {
            doc /* Perform recursive mass rollup calculation
                   bottom-up through the composition tree.
                   Each composite's mass = sum of children. */
        }

        action computeDryMass {
            doc /* For each vehicle subtree, subtract the mass
                   of parts with isConsumable = true. */
        }

        action evaluateRequirements {
            doc /* Compare computed mass values against each
                   mass requirement's threshold limit.
                   Record actual, limit, and PASS/FAIL. */
        }

        return verdict : VerdictKind;
    }

    verification def DeltaVVerification {
        doc /* Verifies delta-v requirements by computing stage
               delta-v using the Tsiolkovsky rocket equation with
               parameters extracted from the architecture model
               and staging sequence from MissionContext.

               Procedure:
               1. Read specificImpulse from PropulsiveStage parts
               2. Determine staging sequence from MissionContext
               3. Compute m_initial for each stage:
                  - TV: full system mass (TV + Lander)
                  - LN: lander-only mass (after TV separation)
               4. Compute m_final = m_initial - propellant mass
               5. Apply deltaV = Isp * g0 * ln(m_i / m_f)
               6. Compare against REQ-TV-DV-001, REQ-LN-DV-001 */

        subject stageUnderTest : SpacecraftDefinitions::PropulsiveStage;

        action identifyStagingOrder {
            doc /* Read MissionContext to determine burn order.
                   TV fires first with full stack attached.
                   LN fires after TV separation. */
        }

        action computeStageMassRatio {
            doc /* Determine initial and final mass for the
                   propulsive stage burn sequence. Account for
                   staging by using correct initial mass. */
        }

        action applyTsiolkovskyEquation {
            doc /* Apply deltaV = Isp * g0 * ln(m_i / m_f)
                   where g0 = 9.80665 m/s^2 */
        }

        action evaluateDeltaVMargin {
            doc /* Compare computed delta-v against the minimum
                   requirement threshold. Report margin. */
        }

        return verdict : VerdictKind;
    }

    verification def PowerVerification {
        doc /* Verifies power margin requirements by summing
               generation and consumption across each vehicle
               subtree and computing the margin.

               Procedure:
               1. Sum powerGeneration attributes in vehicle subtree
               2. Sum powerConsumption attributes in vehicle subtree
               3. Margin = generation - consumption
               4. Compare against REQ-TV-PWR-001, REQ-LN-PWR-001 */

        subject vehicleUnderTest : SpacecraftDefinitions::SpacecraftComponent;

        action aggregatePowerGeneration {
            doc /* Recursively sum powerGeneration across
                   all parts in the vehicle subtree. Include
                   only orbit-average values, not peak. */
        }

        action aggregatePowerConsumption {
            doc /* Recursively sum powerConsumption across
                   all parts in the vehicle subtree. Include
                   only orbit-average values, not peak. */
        }

        action computeMargin {
            doc /* Margin = total generation - total consumption.
                   Must be positive for PASS. */
        }

        return verdict : VerdictKind;
    }

    verification def PayloadVerification {
        doc /* Verifies payload capacity requirement by reading
               the mass attribute of the payload part.

               Procedure:
               1. Find the lnPayload part in the architecture
               2. Read its mass attribute
               3. Compare against REQ-PAY-001 minimum */

        subject payloadModule : SpacecraftDefinitions::SpacecraftComponent;

        action readPayloadMass {
            doc /* Read mass attribute from lnPayload part.
                   Do NOT use designMass (which is 2000 kg,
                   the original target, not the as-built value). */
        }

        action evaluatePayloadReq {
            doc /* Compare actual payload mass against minimum.
                   PASS if actual >= limit. */
        }

        return verdict : VerdictKind;
    }

    /* ---- Verification matrix reference ---- */

    /* The complete V&V matrix cross-references all 8 requirements
       to their verification methods and responsible engineers:

       REQ-SYS-001  | Analysis (mass rollup)       | SE Lead
       REQ-TV-001   | Analysis (dry mass calc)      | TV Lead
       REQ-LN-001   | Analysis (dry mass calc)      | LN Lead
       REQ-TV-DV-001| Analysis (Tsiolkovsky)        | Propulsion
       REQ-LN-DV-001| Analysis (Tsiolkovsky)        | Propulsion
       REQ-TV-PWR-001| Analysis (power budget)      | EPS Lead
       REQ-LN-PWR-001| Analysis (power budget)      | EPS Lead
       REQ-PAY-001  | Analysis (mass measurement)   | Payload Lead
    */
}
