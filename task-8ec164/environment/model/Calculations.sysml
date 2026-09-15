/* Selene Calculation Definitions
 * Reusable calculation definitions for spacecraft analysis.
 *
 *
 * These calculation definitions specify the mathematical models
 * used to evaluate system performance. The agent must discover
 * and implement these equations by reading this file. Note that
 * the Tsiolkovsky equation requires careful attention to the
 * staging sequence described in MissionContext.sysml to determine
 * correct initial and final masses for each stage.
 */

package SeleneCalculations {

    private import ScalarValues::Real;
    private import NumericalFunctions::Ln;
    private import NumericalFunctions::Sqrt;
    private import NumericalFunctions::Exp;

    /* Recursive mass rollup calculation.
     * Computes total mass of a composite part by summing
     * the masses of all leaf-level children. */
    calc def MassRollup {
        doc /* For leaf parts (no children), totalMass equals the
               part's own mass attribute. For composite parts,
               totalMass is the sum of all children's totalMass
               values, computed recursively down the tree.

               IMPORTANT: Only the "mass" attribute contributes
               to the rollup. Other mass-related attributes
               (designMass, allocatedMass, contingencyMass) are
               design parameters and must not be included. */
        in partMasses : Real[0..*];
        return totalMass : Real;
    }

    /* Tsiolkovsky rocket equation for delta-v computation.
     * Fundamental equation of astronautics relating velocity change
     * to propellant mass fraction and exhaust velocity. */
    calc def TsiolkovskyDeltaV {
        doc /* deltaV = specificImpulse * g0 * ln(mInitial / mFinal)

               where:
                 g0 = 9.80665 m/s^2 (standard gravitational
                      acceleration at sea level)
                 specificImpulse = vacuum Isp of the propulsive
                      stage (in seconds)
                 mInitial = total mass at ignition (depends on
                      staging sequence: see MissionContext)
                 mFinal = mInitial minus consumed propellant mass
                      (mass of parts with isConsumable = true in
                      the propulsive stage subtree)

               For the transfer vehicle: mInitial is the FULL STACK
               mass (TV + Lander), because TV burns while mated.
               For the lander: mInitial is the LANDER-ONLY mass
               (after TV separation). */
        in specificImpulse : Real;
        in mInitial : Real;
        in mFinal : Real;
        attribute g0 : Real = 9.80665;
        return deltaV : Real = specificImpulse * g0 * Ln(mInitial / mFinal);
    }

    /* Power budget computation across subsystem hierarchy.
     * Aggregates generation and consumption values from attributes. */
    calc def PowerBudget {
        doc /* Generation: sum of all "powerGeneration" attribute values
               across the entire vehicle subtree.
               Consumption: sum of all "powerConsumption" attribute values
               across the entire vehicle subtree.
               Margin: generation minus consumption.

               Only orbit-average steady-state values are used.
               Do NOT include peakPowerDraw, peakPowerBOL,
               peakDischargePower, heaterPeakPower, or other
               transient/peak attributes in the budget. A negative
               margin indicates a power deficit requiring action. */
        in generationValues : Real[0..*];
        in consumptionValues : Real[0..*];
        return generation : Real;
        return consumption : Real;
        return margin : Real;
    }

    /* Dry mass computation for propulsive subsystems.
     * Removes consumable propellant from total mass. */
    calc def DryMassCalculation {
        doc /* Dry mass = totalMass - consumableMass, where
               consumableMass is the sum of mass attributes for
               all parts in the vehicle subtree where the
               isConsumable attribute is true.

               This means tank mass, engine mass, and structural
               mass are all included in dry mass (they are not
               consumable). Only propellant with isConsumable=true
               is subtracted. */
        in totalMass : Real;
        in consumableMass : Real;
        return dryMass : Real = totalMass - consumableMass;
    }

    /* ---- Additional calculation definitions for reference ---- */

    /* Hohmann transfer delta-v for circular orbit change */
    calc def HohmannTransferDV {
        doc /* Not used directly in requirements verification,
               but provided for trajectory analysis reference.
               deltaV1 = sqrt(mu/r1) * (sqrt(2*r2/(r1+r2)) - 1)
               deltaV2 = sqrt(mu/r2) * (1 - sqrt(2*r1/(r1+r2)))
               totalDeltaV = |deltaV1| + |deltaV2| */
        in mu : Real;
        in r1 : Real;
        in r2 : Real;
        return deltaV1 : Real;
        return deltaV2 : Real;
        return totalDeltaV : Real;
    }

    /* Gravity loss estimate for powered descent */
    calc def GravityLoss {
        doc /* Approximate gravity loss during powered descent.
               gravityLoss = g_surface * burnTime * sin(gamma_avg)
               where g_surface = 1.625 m/s^2 for the Moon. */
        in surfaceGravity : Real = 1.625;
        in burnTime : Real;
        in avgFlightPathAngle : Real;
        return gravityLoss : Real;
    }

    /* Propellant mass fraction for structural assessment */
    calc def PropellantMassFraction {
        doc /* PMF = propellantMass / totalMass
               Higher PMF indicates better structural efficiency.
               Typical values: 0.85-0.92 for stages. */
        in propellantMass : Real;
        in totalMass : Real;
        return pmf : Real = propellantMass / totalMass;
    }

    /* ---- Analysis Case Definitions ---- */

    analysis def SystemMassAnalysis {
        doc /* Formal analysis case for system mass verification.
               Implements recursive mass rollup and compares
               results against all mass-related requirements. */

        subject systemModel : SpacecraftDefinitions::LunarCargoDeliverySystem;

        objective verifyMassBudget {
            doc /* Demonstrate that total system mass, TV dry mass,
                   and lander dry mass all satisfy their respective
                   requirement thresholds. */
        }

        action rollupMasses {
            doc /* Walk the part hierarchy bottom-up. For each
                   composite part, sum children's mass values.
                   For leaf parts, use the mass attribute directly. */
        }

        action computeDryMasses {
            doc /* For each vehicle subtree, subtract the mass of
                   all parts where isConsumable = true from the
                   total vehicle mass. */
        }

        action evaluateMassRequirements {
            doc /* Compare rolled-up mass against REQ-SYS-001.
                   Compare TV dry mass against REQ-TV-001.
                   Compare LN dry mass against REQ-LN-001. */
        }

        return massReport : Real[0..*];
    }

    analysis def PropulsionPerformanceAnalysis {
        doc /* Formal analysis case for propulsion verification.
               Computes delta-v for each propulsive stage using
               the Tsiolkovsky equation and staging sequence. */

        subject propulsionSystem : SpacecraftDefinitions::PropulsiveStage;

        action determineStagingSequence {
            doc /* Identify the order of burns from MissionContext:
                   1. TV burns with full stack as initial mass
                   2. TV separation (no propulsion)
                   3. Lander burns with lander-only initial mass
                   The staging sequence determines m_initial. */
        }

        action computeStagePerformance {
            doc /* For each propulsive stage, apply:
                   deltaV = Isp * g0 * ln(m_initial / m_final)
                   where m_final = m_initial - propellant_mass. */
        }

        return deltaVReport : Real[0..*];
    }

    /* Trade study definition for engine selection (reference only) */
    analysis def EngineTradeStudy {
        doc /* Historical trade study from Phase A comparing
               bipropellant vs electric propulsion for transfer.
               Conclusion: bipropellant selected for shorter
               transfer time despite lower Isp. */

        objective minimizeTransferTime;

        action evaluateBipropOption {
            doc /* Isp=321s, thrust=22kN, transfer time ~4.5 days */
        }

        action evaluateElectricOption {
            doc /* Isp=1800s, thrust=0.5N, transfer time ~270 days */
        }

        return selectedOption : String;
    }
}
