// Selene Lunar Cargo Delivery System
// SysML v2 Textual Notation - Reusable Type Definitions

package SpacecraftDefinitions {

    private import ScalarValues::Real;
    private import ScalarValues::Boolean;
    private import ScalarValues::String;
    private import ScalarValues::Integer;

    /* Enumeration for classifying spacecraft subsystems */
    enum def SubsystemType {
        enum structure;
        enum propulsion;
        enum power;
        enum avionics;
        enum communications;
        enum thermal;
        enum payload;
        enum landingGear;
    }

    /* Maturity levels for components in design lifecycle */
    enum def MaturityLevel {
        enum conceptual;
        enum preliminary;
        enum detailed;
        enum qualified;
        enum flightProven;
    }

    /* Thermal regime classification for mission phases */
    enum def ThermalRegime {
        enum cryogenic;
        enum coldCase;
        enum nominal;
        enum hotCase;
        enum ablative;
    }

    /* Base attribute definition for mass tracking */
    attribute def MassProperty {
        attribute dryMass : Real;
        attribute wetMass : Real;
    }

    /* Heritage and Technology Readiness Level tracking */
    attribute def HeritageData {
        attribute trl : Integer;
        attribute heritageProgram : String;
    }

    /* Thermal material property attribute set */
    attribute def ThermalProperty {
        attribute minOperatingTemp : Real;
        attribute maxOperatingTemp : Real;
        attribute thermalConductivity : Real;
    }

    /* Structural margin attribute set */
    attribute def StructuralMargin {
        attribute yieldStrength : Real;
        attribute ultimateStrength : Real;
        attribute factorOfSafety : Real;
    }

    /* Base part definition for all spacecraft components.
       Every component has a mass attribute in kilograms.
       NOTE: The "mass" attribute represents the as-built
       physical mass of the component. Other mass-like
       attributes (designMass, maxAllowableMass, allocatedMass)
       are design margins and shall NOT be used for rollup. */
    abstract part def SpacecraftComponent {
        attribute mass : Real;
    }

    /* Propulsive stage with engine performance parameters.
       Thrust in Newtons, specific impulse in seconds.
       The specificImpulse attribute is vacuum Isp; sea-level
       Isp is tracked separately for launch-phase analysis. */
    part def PropulsiveStage :> SpacecraftComponent {
        attribute thrust : Real;
        attribute specificImpulse : Real;
    }

    /* Power-generating component (solar arrays, batteries).
       powerGeneration is end-of-life (EOL) worst-case value. */
    part def PowerGeneratingComponent :> SpacecraftComponent {
        attribute powerGeneration : Real;
    }

    /* Power-consuming component (avionics, comms, thermal).
       powerConsumption is orbit-average steady-state draw. */
    part def PowerConsumingComponent :> SpacecraftComponent {
        attribute powerConsumption : Real;
    }

    /* Propellant that is consumed during propulsive burns.
       isConsumable distinguishes propellant from dry mass. */
    part def ConsumablePropellant :> SpacecraftComponent {
        attribute isConsumable : Boolean = true;
    }

    /* Composite power subsystem containing generators */
    part def PowerSubsystem :> SpacecraftComponent;

    /* Top-level vehicle type definitions */
    part def TransferVehicle :> SpacecraftComponent;
    part def Lander :> SpacecraftComponent;
    part def LunarCargoDeliverySystem;

    /* ---- Port Definitions ---- */

    port def CommandDataPort {
        attribute dataRate : Real;
        attribute protocol : String;
    }

    port def TelemetryPort {
        attribute dataRate : Real;
        attribute encoding : String;
    }

    port def PowerPort {
        attribute voltage : Real;
        attribute maxCurrent : Real;
    }

    port def PropellantPort {
        attribute maxFlowRate : Real;
        attribute operatingPressure : Real;
    }

    port def ThermalPort {
        attribute heatFlux : Real;
        attribute emissivity : Real;
    }

    port def MechanicalPort {
        attribute boltPattern : String;
        attribute preload : Real;
    }

    /* ---- Connection Definitions ---- */

    connection def DataLink {
        end source : CommandDataPort;
        end sink : TelemetryPort;
        attribute bandwidth : Real;
        attribute latency : Real;
    }

    connection def PowerBus {
        end supply : PowerPort;
        end load : PowerPort;
        attribute efficiency : Real;
        attribute cableLength : Real;
        attribute cableMass : Real;
    }

    connection def PropellantFeed {
        end upstream : PropellantPort;
        end downstream : PropellantPort;
        attribute lineInnerDiameter : Real;
        attribute maxPressureDrop : Real;
    }

    connection def ThermalCoupling {
        end hotSide : ThermalPort;
        end coldSide : ThermalPort;
        attribute thermalConductance : Real;
    }

    connection def StructuralAttachment {
        end primary : MechanicalPort;
        end secondary : MechanicalPort;
        attribute hasSeparationMechanism : Boolean;
    }

    /* ---- Interface Definitions ---- */

    interface def VehicleSeparationInterface {
        end retainedSide : MechanicalPort;
        end jettisonedSide : MechanicalPort;
        attribute separationDeltaV : Real;
        attribute pyroRedundancy : Integer;
    }

    interface def UmbilicalInterface {
        end vehicleSide : PowerPort;
        end groundSide : PowerPort;
        attribute disconnectForce : Real;
    }

    /* ---- Item Definitions ---- */

    item def Propellant {
        attribute oxidizer : String;
        attribute fuel : String;
        attribute mixtureRatio : Real;
    }

    item def ElectricalPower {
        attribute busVoltage : Real;
        attribute regulationType : String;
    }

    item def ThermalEnergy {
        attribute temperature : Real;
        attribute entropy : Real;
    }

    item def CommandMessage {
        attribute priority : Integer;
        attribute payloadSize : Integer;
    }

    /* ---- Constraint Definitions ---- */

    constraint def MassConstraint {
        in totalMass : Real;
        in massLimit : Real;
        require constraint { totalMass <= massLimit }
    }

    constraint def ThermalEquilibrium {
        in solarFlux : Real;
        in albedoFlux : Real;
        in irFlux : Real;
        in internalDissipation : Real;
        in radiatorArea : Real;
        in emissivity : Real;
        in stefanBoltzmann : Real = 5.67e-8;
        require constraint {
            (solarFlux + albedoFlux + irFlux + internalDissipation)
            <= (radiatorArea * emissivity * stefanBoltzmann * 300.0 * 300.0 * 300.0 * 300.0)
        }
    }

    constraint def StructuralLoadConstraint {
        in appliedLoad : Real;
        in allowableLoad : Real;
        in factorOfSafety : Real;
        require constraint { appliedLoad * factorOfSafety <= allowableLoad }
    }

    constraint def LinkBudgetConstraint {
        in eirp : Real;
        in pathLoss : Real;
        in antennaGain : Real;
        in systemNoiseFigure : Real;
        in requiredEbN0 : Real;
        require constraint { eirp - pathLoss + antennaGain - systemNoiseFigure >= requiredEbN0 }
    }

    /* ---- State Definitions ---- */

    state def MissionPhase {
        entry; then prelaunch;

        state prelaunch;
        state ascent;
        state coastToMoon;
        state lunarOrbitInsertion;
        state lunarOrbit;
        state poweredDescent;
        state terminalDescent;
        state surfaceOps;
    }

    state def OperationalMode {
        entry; then safeMode;

        state safeMode;
        state nominalMode;
        state contingencyMode;
        state lowPowerMode;
    }

    state def PropulsionMode {
        entry; then idle;

        state idle;
        state primed;
        state firing;
        state shutdown;
        state safed;
    }

    /* ---- Metadata Definitions ---- */

    metadata def ModelVersion {
        attribute version : String;
        attribute lastModified : String;
        attribute author : String;
        attribute reviewStatus : String;
    }

    metadata def ComponentMaturity {
        attribute trl : Integer;
        attribute maturityLevel : MaturityLevel;
        attribute qualificationStatus : String;
    }
}
