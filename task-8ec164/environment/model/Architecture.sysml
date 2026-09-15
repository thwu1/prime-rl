/* Selene System Architecture
 * Defines the physical decomposition with mass, power, and propulsion attributes.
 * All mass values in kg, power in W, thrust in N, Isp in seconds.
 *
 *
 * IMPORTANT: The "mass" attribute on each part represents the
 * as-built physical mass. Other attributes with "mass" in their
 * name (e.g., allocatedMass, maxAllowableMass, designMass,
 * contingencyMass) are design parameters and must NOT be used
 * in mass rollup calculations. Only "mass" feeds the rollup.
 *
 * Similarly, "powerGeneration" and "powerConsumption" are the
 * orbit-average steady-state values used in the power budget.
 * Peak, transient, and duty-cycled power values are tracked
 * separately and must not be summed into the budget.
 */

package SeleneArchitecture {

    import SpacecraftDefinitions::*;

    /* ---- Model metadata annotation ---- */
    @ModelVersion {
        attribute version = "3.2.1";
        attribute lastModified = "2026-04-15";
        attribute author = "Selene SE Team";
        attribute reviewStatus = "CDR-Approved";
    }

    part seleneSystem : LunarCargoDeliverySystem {

        doc /* The Selene system comprises two major vehicle elements:
               a transfer vehicle and a lander, stacked vertically.
               The transfer vehicle provides propulsion for Earth
               departure and lunar orbit insertion. The lander
               provides powered descent and surface operations. */

        /* Overall system design parameters (NOT for rollup) */
        attribute allocatedMass : Real = 16500.0;
        attribute maxAllowableMass : Real = 18000.0;
        attribute systemDesignMargin : Real = 0.12;

        /* ============================================
         * Transfer Vehicle - performs trans-lunar injection
         * and lunar orbit insertion maneuvers
         * ============================================ */
        part transferVehicle : TransferVehicle {

            doc /* Transfer vehicle burns while mated to the lander,
                   so its initial mass for delta-v calculation is the
                   full stack mass (TV + Lander). After propellant
                   depletion, the TV is jettisoned. */

            /* TV design parameters (NOT for rollup) */
            attribute designMass : Real = 6200.0;
            attribute contingencyMass : Real = 192.0;
            attribute allocatedMass : Real = 6500.0;

            part tvStructure : SpacecraftComponent {
                // Primary structural bus, harness, and brackets
                attribute mass : Real = 320.0;
                attribute designMass : Real = 350.0;
                attribute structuralSafetyFactor : Real = 2.5;
                attribute firstModeFrequency : Real = 35.0;
            }

            part tvPropulsion : PropulsiveStage {
                attribute thrust : Real = 22000.0;
                attribute specificImpulse : Real = 321.0;
                attribute seaLevelIsp : Real = 289.0;
                attribute chambePressure : Real = 8.6e6;
                attribute nozzleExpansionRatio : Real = 80.0;
                attribute nominalBurnDuration : Real = 412.0;

                part tvEngine : SpacecraftComponent {
                    attribute mass : Real = 75.0;
                    attribute designMass : Real = 80.0;
                    attribute peakPowerDraw : Real = 250.0;
                }
                part tvPropellantTank : SpacecraftComponent {
                    attribute mass : Real = 95.0;
                    attribute tankVolume : Real = 4.82;
                    attribute maxExpectedOperatingPressure : Real = 2.4e6;
                    attribute burstPressure : Real = 6.0e6;
                }
                part tvPropellant : ConsumablePropellant {
                    attribute mass : Real = 5400.0;
                    attribute isConsumable : Boolean = true;
                    attribute density : Real = 1120.0;
                    attribute mixtureRatio : Real = 1.65;
                }
            }

            part tvPower : PowerSubsystem {
                doc /* TV power subsystem sized for cruise phase
                       operations. Solar arrays are body-mounted
                       with single-axis sun tracking. */
                part tvSolarArray : PowerGeneratingComponent {
                    attribute mass : Real = 28.0;
                    attribute powerGeneration : Real = 2400.0;
                    attribute peakPowerBOL : Real = 3100.0;
                    attribute degradationRate : Real = 0.025;
                    attribute arrayArea : Real = 8.4;
                }
                part tvBattery : PowerGeneratingComponent {
                    attribute mass : Real = 38.0;
                    attribute powerGeneration : Real = 480.0;
                    attribute peakDischargePower : Real = 1200.0;
                    attribute energyCapacity : Real = 2400.0;
                    attribute cycleLife : Real = 5000.0;
                }
            }

            part tvAvionics : PowerConsumingComponent {
                attribute mass : Real = 22.0;
                attribute powerConsumption : Real = 165.0;
                attribute peakPowerDraw : Real = 310.0;
                attribute processingCapacity : Real = 400.0;
                attribute radiationTolerance : Real = 100.0;
            }

            part tvComms : PowerConsumingComponent {
                attribute mass : Real = 12.0;
                attribute powerConsumption : Real = 95.0;
                attribute peakPowerDraw : Real = 180.0;
                attribute transmitFrequency : Real = 8.45e9;
                attribute antennaGain : Real = 36.5;
                attribute dataRateMax : Real = 2.0e6;

                port cmdPort : CommandDataPort;
                port tlmPort : TelemetryPort;
            }

            part tvThermal : PowerConsumingComponent {
                attribute mass : Real = 18.0;
                attribute powerConsumption : Real = 65.0;
                attribute heaterPeakPower : Real = 140.0;
                attribute radiatorArea : Real = 2.1;
                attribute radiatorEmissivity : Real = 0.85;
            }

            /* Ports for inter-vehicle interfaces */
            port tvSepPort : MechanicalPort;
            port tvPowerOut : PowerPort;
            port tvDataLink : CommandDataPort;
        }

        /* ============================================
         * Lander - performs powered descent and landing
         * on the lunar surface
         * ============================================ */
        part lander : Lander {

            doc /* The lander performs independently after TV separation.
                   Its initial mass for delta-v is its own total mass
                   (not the full stack). Lander is a single-stage
                   vehicle with no separation events during descent. */

            /* Lander design parameters (NOT for rollup) */
            attribute designMass : Real = 11500.0;
            attribute contingencyMass : Real = 440.0;
            attribute allocatedMass : Real = 12000.0;

            part lnStructure : SpacecraftComponent {
                // Descent stage structural frame and truss
                attribute mass : Real = 410.0;
                attribute designMass : Real = 450.0;
                attribute structuralSafetyFactor : Real = 2.0;
                attribute firstModeFrequency : Real = 25.0;
            }

            part lnPropulsion : PropulsiveStage {
                attribute thrust : Real = 45000.0;
                attribute specificImpulse : Real = 315.0;
                attribute minThrottleLevel : Real = 0.10;
                attribute maxThrottleLevel : Real = 1.00;
                attribute thrustVectorRange : Real = 6.0;
                attribute nominalBurnDuration : Real = 720.0;

                part lnDescentEngine : SpacecraftComponent {
                    attribute mass : Real = 105.0;
                    attribute designMass : Real = 115.0;
                    attribute peakPowerDraw : Real = 400.0;
                }
                part lnPropellantTank : SpacecraftComponent {
                    attribute mass : Real = 165.0;
                    attribute tankVolume : Real = 6.96;
                    attribute maxExpectedOperatingPressure : Real = 2.1e6;
                    attribute burstPressure : Real = 5.25e6;
                }
                part lnPropellant : ConsumablePropellant {
                    attribute mass : Real = 7800.0;
                    attribute isConsumable : Boolean = true;
                    attribute density : Real = 1120.0;
                    attribute mixtureRatio : Real = 1.65;
                }
            }

            part lnLandingGear : SpacecraftComponent {
                // Four-leg deployable landing gear with crushable attenuators
                attribute mass : Real = 195.0;
                attribute designMass : Real = 210.0;
                attribute deploymentForce : Real = 450.0;
                attribute strokeLength : Real = 0.45;
                attribute maxSinkRate : Real = 3.0;
                attribute legSpan : Real = 4.2;
            }

            part lnPower : PowerSubsystem {
                doc /* Lander power subsystem sized for both descent
                       and 14-day surface operations. Arrays are
                       deployed after landing. */
                part lnSolarArray : PowerGeneratingComponent {
                    attribute mass : Real = 42.0;
                    attribute powerGeneration : Real = 3500.0;
                    attribute peakPowerBOL : Real = 4200.0;
                    attribute degradationRate : Real = 0.020;
                    attribute arrayArea : Real = 12.6;
                }
                part lnBattery : PowerGeneratingComponent {
                    attribute mass : Real = 58.0;
                    attribute powerGeneration : Real = 720.0;
                    attribute peakDischargePower : Real = 2000.0;
                    attribute energyCapacity : Real = 4800.0;
                    attribute cycleLife : Real = 8000.0;
                }
            }

            part lnAvionics : PowerConsumingComponent {
                attribute mass : Real = 35.0;
                attribute powerConsumption : Real = 245.0;
                attribute peakPowerDraw : Real = 520.0;
                attribute processingCapacity : Real = 800.0;
                attribute radiationTolerance : Real = 100.0;
            }

            part lnComms : PowerConsumingComponent {
                attribute mass : Real = 18.0;
                attribute powerConsumption : Real = 130.0;
                attribute peakPowerDraw : Real = 260.0;
                attribute transmitFrequency : Real = 8.45e9;
                attribute antennaGain : Real = 28.0;
                attribute dataRateMax : Real = 1.0e6;

                port cmdPort : CommandDataPort;
                port tlmPort : TelemetryPort;
            }

            part lnThermal : PowerConsumingComponent {
                attribute mass : Real = 32.0;
                attribute powerConsumption : Real = 95.0;
                attribute heaterPeakPower : Real = 280.0;
                attribute radiatorArea : Real = 3.8;
                attribute radiatorEmissivity : Real = 0.88;
            }

            part lnPayload : SpacecraftComponent {
                // Scientific and infrastructure payload module
                attribute mass : Real = 2200.0;
                attribute designMass : Real = 2000.0;
                attribute payloadVolume : Real = 2.4;
                attribute operatingPowerMax : Real = 350.0;
            }

            /* Ports for inter-vehicle interfaces */
            port lnSepPort : MechanicalPort;
            port lnPowerIn : PowerPort;
            port lnDataLink : TelemetryPort;
        }

        /* ============================================
         * Inter-vehicle connections and interfaces
         * ============================================ */

        connection tvToLnSeparation : StructuralAttachment {
            doc /* Primary structural attachment between TV and Lander.
                   Separation mechanism fires after TV propellant depletion
                   to release the lander for independent descent. */
            end primary = transferVehicle.tvSepPort;
            end secondary = lander.lnSepPort;
            attribute hasSeparationMechanism : Boolean = true;
        }

        connection tvToLnPower : PowerBus {
            doc /* Cross-vehicle power feed allows TV solar arrays
                   to supplement lander during cruise phase when
                   lander arrays are stowed. */
            end supply = transferVehicle.tvPowerOut;
            end load = lander.lnPowerIn;
            attribute efficiency : Real = 0.94;
            attribute cableLength : Real = 2.8;
            attribute cableMass : Real = 1.2;
        }

        connection tvToLnData : DataLink {
            doc /* Inter-vehicle command and telemetry data bus.
                   Used during mated operations for coordinated
                   navigation and attitude control. */
            end source = transferVehicle.tvDataLink;
            end sink = lander.lnDataLink;
            attribute bandwidth : Real = 10.0e6;
            attribute latency : Real = 0.001;
        }

        interface seleneToLVSepInterface : VehicleSeparationInterface {
            doc /* Launch vehicle separation interface. Clampband
                   release mechanism with redundant pyrotechnic
                   initiators. */
            attribute separationDeltaV : Real = 0.3;
            attribute pyroRedundancy : Integer = 2;
        }
    }

    /* ---- Variant Configuration: High-Energy Transfer Option ---- */
    /* This variant was studied in Phase A but NOT selected for
       baseline design. It uses a higher-Isp engine at reduced
       thrust. These values must NOT be included in the baseline
       analysis; they are retained for trade study reference only.

    variant package HighEnergyTransferOption {
        attribute variantIsp : Real = 465.0;
        attribute variantThrust : Real = 3500.0;
        attribute variantEngineMass : Real = 45.0;
        attribute variantPropellantMass : Real = 2100.0;
    }
    */
}
