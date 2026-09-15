package SystemArchitecture {
    private import CoreDefinitions::*;
    private import SubsystemDefinitions::*;
    private import Requirements::*;
    private import Functions::*;
    private import ScalarValues::*;

    /* ===== SentinelSat System Configuration ===== */

    part sentinelSat : Subsystem {
        doc /* SentinelSat - A medium-class remote sensing satellite
             * for Earth observation in low Earth orbit.
             * Designed for a 5-year mission at 620 km altitude. */

        attribute redefines massBudget = 250.0;
        attribute redefines powerBudget = 510.0;

        /* ---- Payload ---- */
        part payloadSubsystem : PayloadSubsystem {
            attribute redefines massBudget = 90.0;
            attribute redefines powerBudget = 350.0;

            part redefines opticalImager {
                attribute redefines mass = 45.0;
                attribute redefines powerConsumption = 120.0;
                attribute redefines resolution = 0.5;
                attribute redefines focalLength = 1200.0;
                attribute redefines voltage = 28.0;
                attribute redefines current = 4.3;
                attribute redefines dataRate = 800.0;
            }

            part redefines sarUnit {
                attribute redefines mass = 30.0;
                attribute redefines powerConsumption = 200.0;
                attribute redefines swathWidth = 25.0;
                attribute redefines frequency = 9.65;
                attribute redefines voltage = 28.0;
                attribute redefines current = 7.1;
                attribute redefines dataRate = 500.0;
            }

            part redefines dataRecorder {
                attribute redefines mass = 8.0;
                attribute redefines powerConsumption = 15.0;
                attribute redefines storageCapacity = 2.0;
                attribute redefines voltage = 5.0;
                attribute redefines current = 3.0;
            }
        }

        /* ---- Power ---- */
        part powerSubsystem : PowerSubsystem {
            attribute redefines massBudget = 50.0;
            attribute redefines powerBudget = 10.0;

            part redefines solarArray {
                attribute redefines mass = 25.0;
                attribute redefines powerConsumption = 0.0;
                attribute redefines panelArea = 8.5;
                attribute redefines efficiency = 0.30;
                attribute redefines powerOutput = 900.0;
                attribute redefines voltage = 100.0;
                attribute redefines current = 9.0;
            }

            part redefines batteryPack {
                attribute redefines mass = 18.0;
                attribute redefines powerConsumption = 0.0;
                attribute redefines capacity = 40.0;
                attribute redefines voltage = 28.0;
                attribute redefines current = 0.0;
            }

            part redefines powerController {
                attribute redefines mass = 3.0;
                attribute redefines powerConsumption = 5.0;
                attribute redefines voltage = 28.0;
                attribute redefines current = 0.2;
            }
        }

        /* ---- ADCS ---- */
        part adcsSubsystem : ADCSSubsystem {
            attribute redefines massBudget = 15.0;
            attribute redefines powerBudget = 45.0;

            part redefines reactionWheelCluster {
                attribute redefines mass = 12.0;
                attribute redefines powerConsumption = 40.0;
                attribute redefines wheelCount = 4;
                attribute redefines maxTorque = 0.2;
                attribute redefines maxMomentum = 12.0;
            }

            part redefines starTracker {
                attribute redefines mass = 4.0;
                attribute redefines powerConsumption = 10.0;
                attribute redefines fieldOfView = 16.0;
                attribute redefines accuracy = 3.0;
                attribute redefines voltage = 5.0;
                attribute redefines current = 2.0;
            }

            part redefines magnetorquer {
                attribute redefines mass = 2.0;
                attribute redefines powerConsumption = 2.0;
                attribute redefines dipole = 30.0;
                attribute redefines voltage = 12.0;
                attribute redefines current = 0.17;
            }
        }

        /* ---- Communications ---- */
        part commSubsystem : CommSubsystem {
            attribute redefines massBudget = 20.0;
            attribute redefines powerBudget = 80.0;

            part redefines sBandTransponder {
                attribute redefines mass = 5.0;
                attribute redefines powerConsumption = 25.0;
                attribute redefines txPower = 5.0;
                attribute redefines voltage = 28.0;
                attribute redefines current = 0.9;
            }

            part redefines xBandTransmitter {
                attribute redefines mass = 7.0;
                attribute redefines powerConsumption = 50.0;
                attribute redefines txPower = 20.0;
                attribute redefines voltage = 28.0;
                attribute redefines current = 1.8;
                attribute redefines dataRate = 150.0;
            }

            part redefines highGainAntenna {
                attribute redefines mass = 6.0;
                attribute redefines powerConsumption = 0.0;
                attribute redefines diameter = 0.6;
                attribute redefines gain = 34.0;
            }
        }

        /* ---- Propulsion ---- */
        part propulsionSubsystem : PropulsionSubsystem {
            attribute redefines massBudget = 30.0;
            attribute redefines powerBudget = 20.0;

            part redefines thrusterCluster {
                attribute redefines mass = 8.0;
                attribute redefines powerConsumption = 15.0;
                attribute redefines thrustLevel = 22.0;
                attribute redefines specificImpulse = 230.0;
                attribute redefines thrusterCount = 4;
            }

            part redefines propellantTank {
                attribute redefines mass = 15.0;
                attribute redefines powerConsumption = 0.0;
                attribute redefines volume = 45.0;
                attribute redefines maxPressure = 24.0;
            }

            part redefines feedSystem {
                attribute redefines mass = 3.0;
                attribute redefines powerConsumption = 2.0;
                attribute redefines nominalPressure = 22.0;
            }
        }

        /* ---- Structure ---- */
        part structureSubsystem : StructureSubsystem {
            attribute redefines massBudget = 45.0;
            attribute redefines powerBudget = 5.0;

            part redefines primaryBus {
                attribute redefines mass = 35.0;
                attribute redefines powerConsumption = 0.0;
                attribute redefines loadCapacity = 12.0;
            }

            part redefines deploymentMechanism {
                attribute redefines mass = 10.0;
                attribute redefines powerConsumption = 0.0;
                attribute redefines reliability = 0.9995;
            }

            part redefines thermalBlanket {
                attribute redefines mass = 5.0;
                attribute redefines powerConsumption = 0.0;
                attribute redefines minTemp = -20.0;
                attribute redefines maxTemp = 50.0;
            }
        }
    }

    /* ===== Requirement Satisfaction ===== */
    /* Traceability from requirements to satisfying elements */

    satisfy systemMassReq by sentinelSat;
    satisfy systemPowerReq by sentinelSat.powerSubsystem;
    satisfy downlinkRateReq by sentinelSat.commSubsystem;

    satisfy opticalResolutionReq by sentinelSat.payloadSubsystem.opticalImager;
    satisfy sarSwathReq by sentinelSat.payloadSubsystem.sarUnit;
    satisfy dataStorageReq by sentinelSat.payloadSubsystem.dataRecorder;

    satisfy batteryCapacityReq by sentinelSat.powerSubsystem.batteryPack;

    satisfy pointingAccuracyReq by sentinelSat.adcsSubsystem;
    satisfy slewRateReq by sentinelSat.adcsSubsystem.reactionWheelCluster;

    satisfy sBandUplinkReq by sentinelSat.commSubsystem.sBandTransponder;
    satisfy xBandDownlinkReq by sentinelSat.commSubsystem.xBandTransmitter;

    satisfy deltaVReq by sentinelSat.propulsionSubsystem;

    satisfy launchLoadReq by sentinelSat.structureSubsystem.primaryBus;
    satisfy thermalControlReq by sentinelSat.structureSubsystem.thermalBlanket;

    /* ===== Function Allocation ===== */
    /* Mapping of mission functions to responsible subsystems */

    allocate performMission.captureOpticalImage to sentinelSat.payloadSubsystem;
    allocate performMission.captureSARImage to sentinelSat.payloadSubsystem;
    allocate performMission.storeData to sentinelSat.payloadSubsystem;
    allocate performMission.downlinkData to sentinelSat.commSubsystem;
    allocate performMission.performOrbitMaintenance to sentinelSat.propulsionSubsystem;
    allocate performMission.pointSpacecraft to sentinelSat.adcsSubsystem;
    allocate performMission.managePower to sentinelSat.powerSubsystem;
}
