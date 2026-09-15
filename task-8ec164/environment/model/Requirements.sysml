/* Selene System Requirements
 * Quantitative requirements for the Selene lunar cargo delivery spacecraft.
 * Each requirement specifies a constraint type and a threshold value.
 *
 *
 * Requirements are organized by domain and level:
 *   - System-level (REQ-SYS-*): applies to entire Selene system
 *   - Transfer Vehicle (REQ-TV-*): applies to TV subsystem
 *   - Lander (REQ-LN-*): applies to lander subsystem
 *   - Payload (REQ-PAY-*): applies to payload delivery
 *
 * Constraint semantics differ by requirement type:
 *   - TotalMassRequirement: actual <= limit (PASS if under limit)
 *   - DryMassRequirement: actual <= limit (PASS if under limit)
 *   - DeltaVRequirement: actual >= limit (PASS if exceeds minimum)
 *   - PowerMarginRequirement: actual >= limit (PASS if exceeds minimum)
 *   - PayloadCapacityRequirement: actual >= limit (PASS if exceeds minimum)
 *
 * NOTE: The massLimit/dryMassLimit/minDeltaV/minMargin/minPayload
 * attributes on each requirement instance define the threshold.
 * Do NOT confuse these with designMass or allocatedMass on parts.
 */

package SeleneRequirements {

    private import ScalarValues::Real;
    private import ScalarValues::String;

    /* ---- Stakeholder needs (informational only, not testable) ---- */

    concern def MissionSuccess {
        doc /* The primary stakeholder concern driving all
               quantitative requirements below. The system shall
               deliver its full payload complement to the lunar
               surface with margins sufficient for off-nominal
               conditions. */
        stakeholder lunarProgramOffice;
    }

    concern def LaunchConstraint {
        doc /* The selected launch vehicle imposes hard constraints
               on total encapsulated mass and volume. Fairing mass
               limit of 16000 kg includes all spacecraft wet mass
               and adapter. This drives REQ-SYS-001. */
        stakeholder launchProvider;
    }

    /* ---- Requirement type definitions ---- */

    requirement def TotalMassRequirement {
        doc /* Constrains the total mass (wet mass including propellant)
               of a system or subsystem. Evaluation: compute total
               mass by recursive rollup of all children's mass attributes.
               Compare against massLimit. Pass if actual <= limit. */
        attribute actualMass : Real;
        attribute massLimit : Real;
        require constraint { actualMass <= massLimit }
    }

    requirement def DryMassRequirement {
        doc /* Constrains the dry mass of a subsystem, defined as
               total mass minus mass of all consumable propellant
               (parts where isConsumable == true). This excludes
               tank mass, engine mass, and other non-consumable
               components from the subtraction.
               Compare against dryMassLimit. Pass if actual <= limit. */
        attribute actualDryMass : Real;
        attribute dryMassLimit : Real;
        require constraint { actualDryMass <= dryMassLimit }
    }

    requirement def DeltaVRequirement {
        doc /* Constrains the minimum delta-v capability of a propulsive
               stage. Delta-v is computed using the Tsiolkovsky rocket
               equation: dv = Isp * g0 * ln(m_initial / m_final) where
               g0 = 9.80665 m/s^2. The initial and final mass depend on
               the staging sequence defined in MissionContext.
               Compare against minDeltaV. Pass if actual >= limit. */
        attribute actualDeltaV : Real;
        attribute minDeltaV : Real;
        require constraint { actualDeltaV >= minDeltaV }
    }

    requirement def PowerMarginRequirement {
        doc /* Constrains the minimum power margin, defined as the
               difference between total powerGeneration and total
               powerConsumption summed across a vehicle's subtree.
               Only orbit-average steady-state values contribute;
               peak and transient values are excluded.
               Compare against minMargin. Pass if actual >= limit. */
        attribute actualMargin : Real;
        attribute minMargin : Real;
        require constraint { actualMargin >= minMargin }
    }

    requirement def PayloadCapacityRequirement {
        doc /* Constrains the minimum payload delivery capacity.
               Payload mass is the mass attribute of the payload
               part, not a computed rollup value.
               Compare against minPayload. Pass if actual >= limit. */
        attribute actualPayload : Real;
        attribute minPayload : Real;
        require constraint { actualPayload >= minPayload }
    }

    /* ---- Withdrawn requirement type (do NOT evaluate) ---- */
    /* The StructuralFrequencyRequirement was withdrawn during
       PDR after modal analysis showed it was non-binding.
       Retained here for document history only.

    requirement def StructuralFrequencyRequirement {
        doc // WITHDRAWN - replaced by coupled loads analysis //
        attribute actualFrequency : Real;
        attribute minFrequency : Real;
        require constraint { actualFrequency >= minFrequency }
    }

    requirement structFreqReq : StructuralFrequencyRequirement id 'REQ-SYS-002' {
        attribute redefines minFrequency = 15.0;
    }
    */

    /* ---- Requirement instances ---- */

    requirement systemMassReq : TotalMassRequirement id 'REQ-SYS-001' {
        doc /* Total system launch mass shall not exceed 16000 kg
               to remain within launch vehicle fairing mass constraints.
               This is the driving system-level requirement. */
        attribute redefines massLimit = 16000.0;
    }

    requirement tvDryMassReq : DryMassRequirement id 'REQ-TV-001' {
        doc /* Transfer vehicle dry mass shall not exceed 700 kg
               to maintain adequate propellant mass fraction for
               the trans-lunar injection delta-v budget. */
        attribute redefines dryMassLimit = 700.0;
    }

    requirement lnDryMassReq : DryMassRequirement id 'REQ-LN-001' {
        doc /* Lander dry mass (total minus consumable propellant)
               shall not exceed 3500 kg to ensure sufficient
               descent delta-v margin above the 3600 m/s requirement. */
        attribute redefines dryMassLimit = 3500.0;
    }

    requirement tvDeltaVReq : DeltaVRequirement id 'REQ-TV-DV-001' {
        doc /* Transfer vehicle shall provide at least 1250 m/s of
               delta-v for combined trans-lunar injection and lunar
               orbit insertion. Initial mass is the full stack mass
               (TV + Lander). */
        attribute redefines minDeltaV = 1250.0;
    }

    requirement lnDeltaVReq : DeltaVRequirement id 'REQ-LN-DV-001' {
        doc /* Lander shall provide at least 3600 m/s of delta-v
               for powered descent from 100 km circular lunar orbit
               to the surface, including gravity losses and
               hover/landing margin. Initial mass is lander-only
               (post TV separation). */
        attribute redefines minDeltaV = 3600.0;
    }

    requirement tvPowerReq : PowerMarginRequirement id 'REQ-TV-PWR-001' {
        doc /* Transfer vehicle power margin shall be at least 500 W
               during cruise to support contingency safe-mode
               operations and battery recharge. */
        attribute redefines minMargin = 500.0;
    }

    requirement lnPowerReq : PowerMarginRequirement id 'REQ-LN-PWR-001' {
        doc /* Lander power margin shall be at least 500 W during
               surface operations to support science payload
               commissioning and data relay. */
        attribute redefines minMargin = 500.0;
    }

    requirement payloadReq : PayloadCapacityRequirement id 'REQ-PAY-001' {
        doc /* System shall deliver at least 2000 kg of payload
               to the lunar surface. Payload mass is measured at
               the payload interface. */
        attribute redefines minPayload = 2000.0;
    }
}
