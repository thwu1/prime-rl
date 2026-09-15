package VerificationCases {
    private import CoreDefinitions::*;
    private import SubsystemDefinitions::*;
    private import Requirements::*;
    private import SystemArchitecture::*;

    /* ===== Verification Case Definitions ===== */
    /* Each definition specifies a verification procedure for a requirement.
     * The subject declares the type of element under test.
     * The objective's verify statement links to the requirement being verified.
     * Constraints from the verified requirement are evaluated against
     * actual attribute values resolved from the bound subject. */

    verification def SystemMassVerification {
        doc /* Verify total satellite mass remains within budget.
             * For MassRequirement: massActual is computed as the sum of
             * all direct subsystem masses within the subject. */
        subject satellite : Subsystem;
        objective massObjective {
            verify systemMassReq;
        }
    }

    verification def PowerGenerationVerification {
        doc /* Verify power generation capacity meets system requirements.
             * For PowerRequirement: powerOutput is resolved from
             * the subject's part hierarchy. */
        subject powerSys : PowerSubsystem;
        objective powerObjective {
            verify systemPowerReq;
        }
    }

    verification def PointingAccuracyVerification {
        doc /* Verify spacecraft pointing accuracy meets requirement.
             * The accuracy attribute from the subject's star tracker
             * is evaluated against the requirement threshold. */
        subject adcsSys : ADCSSubsystem;
        objective pointingObjective {
            verify pointingAccuracyReq;
        }
    }

    verification def StorageCapacityVerification {
        doc /* Verify on-board data storage capacity.
             * The storageCapacity attribute of the data recorder
             * within the subject is compared against threshold. */
        subject payloadSys : PayloadSubsystem;
        objective storageObjective {
            verify dataStorageReq;
        }
    }

    verification def ThrustPerformanceVerification {
        doc /* Verify propulsion specific impulse meets requirement.
             * The specificImpulse attribute of the thruster cluster
             * within the subject is evaluated. */
        subject propSys : PropulsionSubsystem;
        objective thrustObjective {
            verify specificImpulseReq;
        }
    }

    verification def ThermalRangeVerification {
        doc /* Verify thermal control range meets requirement.
             * The minTemp and maxTemp attributes of the thermal blanket
             * within the subject are compared against thresholds. */
        subject structSys : StructureSubsystem;
        objective thermalObjective {
            verify thermalControlReq;
        }
    }

    /* ===== Verification Case Usages ===== */
    /* Each usage binds the definition's subject parameter to a
     * concrete element in the system architecture, enabling
     * constraint evaluation with actual attribute values. */

    verification systemMassCheck : SystemMassVerification {
        subject satellite = sentinelSat;
    }

    verification powerCheck : PowerGenerationVerification {
        subject powerSys = sentinelSat.powerSubsystem;
    }

    verification pointingCheck : PointingAccuracyVerification {
        subject adcsSys = sentinelSat.adcsSubsystem;
    }

    verification storageCheck : StorageCapacityVerification {
        subject payloadSys = sentinelSat.payloadSubsystem;
    }

    verification ispCheck : ThrustPerformanceVerification {
        subject propSys = sentinelSat.propulsionSubsystem;
    }

    verification thermalCheck : ThermalRangeVerification {
        subject structSys = sentinelSat.structureSubsystem;
    }
}
