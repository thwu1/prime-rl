#!/usr/bin/env python3
"""Generate OWL ontology files for hydrological ontology alignment task.


Creates two OWL/RDF-XML ontologies about water resources / environmental
monitoring that share overlapping but differently-modeled concepts.
Includes OWL restriction axioms, false-friend classes, and object properties.
"""
import os
from xml.sax.saxutils import escape

# ── Source ontology: Water Quality Monitoring Ontology (WQMO) ────────────
# Each entry: (class_id, label, [alt_labels], parent_id)
SOURCE_CLASSES = [
    # ── Water Bodies ──
    ("WaterBody", "Water Body", [], None),
    ("SurfaceWater", "Surface Water", ["Surface water body"], "WaterBody"),
    ("River", "River", [], "SurfaceWater"),
    ("Lake", "Lake", [], "SurfaceWater"),
    ("Reservoir", "Reservoir", ["Impoundment"], "SurfaceWater"),
    ("Stream", "Stream", ["Brook"], "SurfaceWater"),
    ("Wetland", "Wetland", ["Marsh"], "SurfaceWater"),
    ("Estuary", "Estuary", ["Estuarine zone"], "SurfaceWater"),
    ("Canal", "Canal", ["Irrigation canal", "Artificial waterway"], "SurfaceWater"),
    ("Pond", "Pond", [], "SurfaceWater"),
    ("Creek", "Creek", [], "SurfaceWater"),
    ("Groundwater", "Groundwater", ["Subsurface water"], "WaterBody"),
    ("Aquifer", "Aquifer", [], "Groundwater"),
    ("UnconfinedAquifer", "Unconfined Aquifer", ["Water-table aquifer", "Phreatic aquifer"], "Aquifer"),
    ("ConfinedAquifer", "Confined Aquifer", ["Artesian aquifer"], "Aquifer"),
    ("Well", "Well", ["Water well", "Borehole"], "Groundwater"),
    ("Spring", "Spring", ["Natural spring", "Groundwater spring"], "Groundwater"),
    ("CoastalWater", "Coastal Water", [], "WaterBody"),
    ("Bay", "Bay", [], "CoastalWater"),
    ("Lagoon", "Lagoon", ["Coastal lagoon"], "CoastalWater"),
    # ── Water Quality Parameters ──
    ("WaterQualityParameter", "Water Quality Parameter", ["WQ parameter"], None),
    ("ChemicalParameter", "Chemical Parameter", [], "WaterQualityParameter"),
    ("pH", "pH", ["Hydrogen ion concentration"], "ChemicalParameter"),
    ("DissolvedOxygen", "Dissolved Oxygen", ["DO"], "ChemicalParameter"),
    ("BOD", "Biochemical Oxygen Demand", ["BOD5"], "ChemicalParameter"),
    ("COD", "Chemical Oxygen Demand", [], "ChemicalParameter"),
    ("TotalDissolvedSolids", "Total Dissolved Solids", ["TDS"], "ChemicalParameter"),
    ("Alkalinity", "Alkalinity", ["Acid neutralizing capacity"], "ChemicalParameter"),
    ("Hardness", "Hardness", ["Water hardness", "Total hardness"], "ChemicalParameter"),
    ("NutrientParameter", "Nutrient Parameter", ["Nutrient indicator"], "WaterQualityParameter"),
    ("Nitrate", "Nitrate", ["NO3"], "NutrientParameter"),
    ("Nitrite", "Nitrite", ["NO2"], "NutrientParameter"),
    ("Ammonia", "Ammonia", ["NH3", "Ammoniacal nitrogen"], "NutrientParameter"),
    ("TotalNitrogen", "Total Nitrogen", ["TN"], "NutrientParameter"),
    ("Phosphate", "Phosphate", ["PO4", "Orthophosphate"], "NutrientParameter"),
    ("TotalPhosphorus", "Total Phosphorus", ["TP"], "NutrientParameter"),
    ("MicrobialParameter", "Microbial Parameter", ["Microbiological parameter"], "WaterQualityParameter"),
    ("TotalColiform", "Total Coliform", [], "MicrobialParameter"),
    ("FecalColiform", "Fecal Coliform", ["Faecal coliform", "Thermotolerant coliform"], "MicrobialParameter"),
    ("EColi", "E. coli", ["Escherichia coli"], "MicrobialParameter"),
    ("Enterococci", "Enterococci", ["Intestinal enterococci"], "MicrobialParameter"),
    ("PhysicalParameter", "Physical Parameter", [], "WaterQualityParameter"),
    ("WaterTemperature", "Water Temperature", [], "PhysicalParameter"),
    ("Turbidity", "Turbidity", ["NTU"], "PhysicalParameter"),
    ("Conductivity", "Conductivity", ["Electrical conductivity", "EC", "Specific conductance"], "PhysicalParameter"),
    ("WaterColor", "Water Color", ["Colour"], "PhysicalParameter"),
    ("FlowRate", "Flow Rate", ["Discharge rate", "Stream discharge"], "PhysicalParameter"),
    ("WaterLevel", "Water Level", ["Stage", "Gauge height"], "PhysicalParameter"),
    ("MetalParameter", "Metal Parameter", ["Heavy metal parameter"], "WaterQualityParameter"),
    ("LeadConc", "Lead Concentration", ["Pb"], "MetalParameter"),
    ("MercuryConc", "Mercury Concentration", ["Hg"], "MetalParameter"),
    ("CadmiumConc", "Cadmium Concentration", ["Cd"], "MetalParameter"),
    ("ArsenicConc", "Arsenic Concentration", ["As"], "MetalParameter"),
    ("ChromiumConc", "Chromium Concentration", ["Cr"], "MetalParameter"),
    ("CopperConc", "Copper Concentration", ["Cu"], "MetalParameter"),
    ("ZincConc", "Zinc Concentration", ["Zn"], "MetalParameter"),
    # ── Contaminants ──
    ("Contaminant", "Contaminant", ["Pollutant"], None),
    ("InorganicContaminant", "Inorganic Contaminant", [], "Contaminant"),
    ("HeavyMetal", "Heavy Metal", ["Toxic metal"], "InorganicContaminant"),
    ("CyanideContam", "Cyanide", [], "InorganicContaminant"),
    ("FluorideContam", "Fluoride", [], "InorganicContaminant"),
    ("OrganicContaminant", "Organic Contaminant", [], "Contaminant"),
    ("Pesticide", "Pesticide", ["Pest control chemical"], "OrganicContaminant"),
    ("Herbicide", "Herbicide", ["Weed killer"], "OrganicContaminant"),
    ("PharmaceuticalCompound", "Pharmaceutical Compound", ["Drug residue"], "OrganicContaminant"),
    ("PFAS", "PFAS", ["Per- and polyfluoroalkyl substance", "Forever chemical"], "OrganicContaminant"),
    ("PCB", "PCB", ["Polychlorinated biphenyl"], "OrganicContaminant"),
    ("PAH", "PAH", ["Polycyclic aromatic hydrocarbon"], "OrganicContaminant"),
    ("EmergingContaminant", "Emerging Contaminant", ["Contaminant of emerging concern"], "Contaminant"),
    ("Microplastic", "Microplastic", ["Microplastic particle"], "EmergingContaminant"),
    ("EndocrineDisruptor", "Endocrine Disruptor", ["EDC"], "EmergingContaminant"),
    ("AMRGene", "Antimicrobial Resistance Gene", ["ARG"], "EmergingContaminant"),
    # ── Monitoring Equipment ──
    ("MonitoringEquipment", "Monitoring Equipment", ["Measurement device"], None),
    ("Sensor", "Sensor", ["In-situ sensor", "Probe"], "MonitoringEquipment"),
    ("pHSensor", "pH Sensor", ["pH probe", "pH meter"], "Sensor"),
    ("DOSensor", "DO Sensor", ["Oxygen sensor"], "Sensor"),
    ("TurbiditySensor", "Turbidity Sensor", ["Nephelometer"], "Sensor"),
    ("ConductivitySensor", "Conductivity Sensor", ["EC probe"], "Sensor"),
    ("MultiparameterProbe", "Multiparameter Probe", ["Multi-sensor sonde"], "Sensor"),
    ("SamplingDevice", "Sampling Device", ["Water sampler"], "MonitoringEquipment"),
    ("GrabSampler", "Grab Sampler", ["Discrete sampler", "Manual sampler"], "SamplingDevice"),
    ("AutoSampler", "Automatic Sampler", ["Auto-sampler", "Time-integrated sampler"], "SamplingDevice"),
    ("PassiveSampler", "Passive Sampler", ["Diffusive sampler"], "SamplingDevice"),
    ("FieldInstrument", "Field Instrument", ["Portable instrument"], "MonitoringEquipment"),
    ("FlowMeter", "Flow Meter", ["Current meter", "Velocity meter"], "FieldInstrument"),
    ("DepthGauge", "Depth Gauge", ["Staff gauge", "Water level gauge"], "FieldInstrument"),
    # ── Stations ──
    ("MonitoringStation", "Monitoring Station", ["Observation station", "Gauging station"], None),
    ("FixedStation", "Fixed Station", ["Permanent station"], "MonitoringStation"),
    ("RiverbankStation", "Riverbank Station", ["Riverside station"], "FixedStation"),
    ("LakeshoreStation", "Lakeshore Station", ["Lakeside station"], "FixedStation"),
    ("OutfallStation", "Outfall Station", ["Effluent monitoring point"], "FixedStation"),
    ("MobileUnit", "Mobile Unit", ["Mobile monitoring platform"], "MonitoringStation"),
    ("BoatUnit", "Boat Unit", ["Vessel-based platform"], "MobileUnit"),
    ("DroneUnit", "Drone Unit", ["UAV platform"], "MobileUnit"),
    # ── Programs ──
    ("SamplingProgram", "Sampling Program", ["Monitoring program", "Surveillance program"], None),
    ("RoutineMonitoring", "Routine Monitoring", ["Periodic surveillance"], "SamplingProgram"),
    ("EventSampling", "Event-based Sampling", ["Storm event sampling"], "SamplingProgram"),
    ("BaselineSurvey", "Baseline Survey", ["Reference condition survey"], "SamplingProgram"),
    ("EmergencyResponse", "Emergency Response", ["Incident response"], "SamplingProgram"),
    # ── Standards ──
    ("WaterQualityStandard", "Water Quality Standard", ["Environmental standard", "Regulatory standard"], None),
    ("DrinkingWaterStandard", "Drinking Water Standard", ["Potable water criterion"], "WaterQualityStandard"),
    ("AquaticLifeStandard", "Aquatic Life Standard", ["Aquatic ecosystem objective"], "WaterQualityStandard"),
    ("RecreationalStandard", "Recreational Standard", ["Bathing water directive"], "WaterQualityStandard"),
    ("IrrigationStandard", "Irrigation Standard", ["Irrigation guideline"], "WaterQualityStandard"),
    ("EffluentStandard", "Effluent Standard", ["Discharge permit limit"], "WaterQualityStandard"),
    # ── Watershed / Land Use ──
    ("Watershed", "Watershed", ["Drainage area", "Catchment area"], None),
    ("RiverBasin", "River Basin", ["Drainage basin", "Main basin"], "Watershed"),
    ("SubBasin", "Sub-Basin", ["Sub-catchment"], "Watershed"),
    ("LandUseType", "Land Use Type", [], None),
    ("UrbanArea", "Urban Area", ["Built-up area"], "LandUseType"),
    ("AgriculturalLand", "Agricultural Land", ["Cropland", "Farmland"], "LandUseType"),
    ("ForestLand", "Forest Land", ["Woodland"], "LandUseType"),
    ("IndustrialArea", "Industrial Area", ["Industrial site"], "LandUseType"),
    ("WetlandUse", "Wetland Area", ["Marshland"], "LandUseType"),
    # ── Pollution Sources ──
    ("PollutionSource", "Pollution Source", ["Contamination source"], None),
    ("PointSource", "Point Source", ["Direct emission source"], "PollutionSource"),
    ("IndustrialDischarge", "Industrial Discharge", ["Industrial effluent", "Factory outfall"], "PointSource"),
    ("MunicipalWastewater", "Municipal Wastewater", ["Sewage", "Domestic wastewater"], "PointSource"),
    ("StormwaterOutfall", "Stormwater Outfall", ["Storm drain outlet"], "PointSource"),
    ("DiffuseSource", "Diffuse Source", ["Non-point source"], "PollutionSource"),
    ("AgriculturalRunoff", "Agricultural Runoff", ["Farm runoff", "Agricultural leaching"], "DiffuseSource"),
    ("UrbanRunoff", "Urban Runoff", ["Urban surface runoff"], "DiffuseSource"),
    ("AtmosphericDeposition", "Atmospheric Deposition", ["Wet deposition", "Acid rain"], "DiffuseSource"),
    # ── Treatment ──
    ("TreatmentProcess", "Treatment Process", ["Water treatment"], None),
    ("Filtration", "Filtration", ["Mechanical filtration"], "TreatmentProcess"),
    ("Chlorination", "Chlorination", ["Chemical disinfection"], "TreatmentProcess"),
    ("UVDisinfection", "UV Disinfection", ["Ultraviolet treatment"], "TreatmentProcess"),
    ("ReverseOsmosis", "Reverse Osmosis", ["Membrane filtration", "RO"], "TreatmentProcess"),
    ("ActivatedCarbon", "Activated Carbon", ["GAC treatment", "Adsorption treatment"], "TreatmentProcess"),
    # ── Ecological concepts ──
    ("AquaticEcosystem", "Aquatic Ecosystem", ["Aquatic habitat"], None),
    ("LenticEcosystem", "Lentic Ecosystem", ["Standing water ecosystem"], "AquaticEcosystem"),
    ("LoticEcosystem", "Lotic Ecosystem", ["Flowing water ecosystem"], "AquaticEcosystem"),
    ("RiparianZone", "Riparian Zone", ["Riparian buffer", "Streamside zone"], "AquaticEcosystem"),
    # ── Biological Indicators ──
    ("BiologicalIndicator", "Biological Indicator", ["Biomonitor"], None),
    ("Macroinvertebrate", "Macroinvertebrate", ["Benthic macroinvertebrate"], "BiologicalIndicator"),
    ("Phytoplankton", "Phytoplankton", ["Algae"], "BiologicalIndicator"),
    ("Periphyton", "Periphyton", ["Attached algae", "Biofilm"], "BiologicalIndicator"),
    # ── Sediment ──
    ("Sediment", "Sediment", [], None),
    ("BedSediment", "Bed Sediment", ["Bottom sediment", "Bed material"], "Sediment"),
    ("SuspendedSediment", "Suspended Sediment", ["Suspended solids", "TSS"], "Sediment"),
    # ── Geomorphology (false-friend context for "Channel") ──
    ("GeomorphFeature", "Geomorphological Feature", [], None),
    ("Floodplain", "Floodplain", ["Flood plain"], "GeomorphFeature"),
    ("RiverChannel", "River Channel", ["Stream channel", "Natural channel"], "GeomorphFeature"),
    ("Delta", "Delta", ["River delta"], "GeomorphFeature"),
    # ── Hydrological Processes ──
    ("HydrologicalProcess", "Hydrological Process", [], None),
    ("Evaporation", "Evaporation", ["Evapotranspiration"], "HydrologicalProcess"),
    ("Precipitation", "Precipitation", ["Rainfall"], "HydrologicalProcess"),
    ("Infiltration", "Infiltration", ["Percolation"], "HydrologicalProcess"),
    ("SurfaceRunoff", "Surface Runoff", ["Overland flow"], "HydrologicalProcess"),
    ("Baseflow", "Baseflow", ["Base flow", "Groundwater contribution"], "HydrologicalProcess"),
    # ── Seasonal Events (false-friend context for "Spring") ──
    ("SeasonalEvent", "Seasonal Event", [], None),
    ("SpringFlood", "Spring Flood", ["Snowmelt flood", "Freshet"], "SeasonalEvent"),
    ("SummerLowFlow", "Summer Low Flow", ["Drought flow"], "SeasonalEvent"),
]

# Restriction-defined classes for source
# Format: (class_id, label, equivalent_class_desc, parent_id)
SOURCE_DEFINED_CLASSES = [
    ("PollutedRiver", "Polluted River", "River AND hasQualityStatus value 'poor'", "River"),
    ("EutrophicLake", "Eutrophic Lake", "Lake AND hasNutrientLevel value 'high'", "Lake"),
    ("PotableSource", "Potable Water Source",
     "SurfaceWater AND meetsStandard some DrinkingWaterStandard", "SurfaceWater"),
    ("ContaminatedAquifer", "Contaminated Aquifer",
     "Aquifer AND hasContaminant some HeavyMetal", "Aquifer"),
    ("MonitoredRiver", "Monitored River",
     "River AND monitoredAt some FixedStation", "River"),
    ("UrbanizedCatchment", "Urbanized Catchment",
     "Watershed AND hasDominantLandUse some UrbanArea", "Watershed"),
    ("AcidifiedWater", "Acidified Water Body",
     "WaterBody AND hasPH value 'low'", "WaterBody"),
    ("ThermallyStressed", "Thermally Stressed Water Body",
     "WaterBody AND hasTemperatureAnomaly value 'true'", "WaterBody"),
]

# Source object properties
# Format: (prop_id, label, [alt_labels], domain_id, range_id)
SOURCE_PROPERTIES = [
    ("hasMeasurement", "has measurement", ["measures"], "WaterBody", "WaterQualityParameter"),
    ("monitoredAt", "monitored at", ["observed at"], "WaterBody", "MonitoringStation"),
    ("locatedIn", "located in", ["within watershed"], "WaterBody", "Watershed"),
    ("hasContaminant", "has contaminant", ["contaminated by"], "WaterBody", "Contaminant"),
    ("meetsStandard", "meets standard", ["compliant with"], "WaterBody", "WaterQualityStandard"),
    ("receivesFrom", "receives from", ["impacted by source"], "WaterBody", "PollutionSource"),
    ("treatedBy", "treated by", ["undergoes treatment"], "WaterBody", "TreatmentProcess"),
    ("sampledUsing", "sampled using", ["collected with"], "SamplingProgram", "SamplingDevice"),
    ("flowsInto", "flows into", ["discharges into"], "WaterBody", "WaterBody"),
    ("hasUpstream", "has upstream", ["receives inflow from"], "WaterBody", "WaterBody"),
    ("hasLandUse", "has land use", ["land cover"], "Watershed", "LandUseType"),
    ("hasEcosystem", "has ecosystem", ["supports habitat"], "WaterBody", "AquaticEcosystem"),
]

# ── Target ontology: Hydrological Resource Ontology (HRO) ───────────────
TARGET_CLASSES = [
    # ── Hydrological Features ──
    ("HydrologicalFeature", "Hydrological Feature", ["Water feature"], None),
    ("FlowingWater", "Flowing Water", ["Lotic water body"], "HydrologicalFeature"),
    ("RiverSystem", "River System", ["River", "Fluvial system"], "FlowingWater"),
    ("StreamSystem", "Stream System", ["Stream"], "FlowingWater"),
    ("CreekSystem", "Creek", [], "FlowingWater"),
    # NOTE: Channel is a NATURAL geomorphic feature here, different from Canal
    ("Channel", "Channel", ["Natural channel", "Watercourse channel"], "FlowingWater"),
    ("StandingWater", "Standing Water", ["Lentic water body"], "HydrologicalFeature"),
    ("NaturalLake", "Natural Lake", ["Lake"], "StandingWater"),
    ("ArtificialReservoir", "Artificial Reservoir", ["Reservoir", "Impoundment"], "StandingWater"),
    ("NaturalPond", "Pond", [], "StandingWater"),
    ("MarshWetland", "Marsh", ["Wetland", "Palustrine wetland"], "StandingWater"),
    ("TransitionalWater", "Transitional Water", ["Estuarine and coastal"], "HydrologicalFeature"),
    ("EstuarineZone", "Estuarine Zone", ["Estuary"], "TransitionalWater"),
    ("CoastalLagoon", "Coastal Lagoon", ["Lagoon"], "TransitionalWater"),
    ("BayArea", "Bay", ["Embayment"], "TransitionalWater"),
    ("SubsurfaceWater", "Subsurface Water", ["Groundwater"], "HydrologicalFeature"),
    ("UnconfinedFormation", "Unconfined Formation", ["Phreatic aquifer", "Unconfined aquifer"], "SubsurfaceWater"),
    ("ConfinedFormation", "Confined Formation", ["Artesian formation", "Confined aquifer"], "SubsurfaceWater"),
    ("WaterWell", "Water Well", ["Borehole", "Production well"], "SubsurfaceWater"),
    ("NaturalSpring", "Natural Spring", ["Spring", "Seep"], "SubsurfaceWater"),
    ("IrrigationCanal", "Irrigation Canal", ["Artificial channel", "Man-made waterway"], "HydrologicalFeature"),
    # ── Environmental Parameters ──
    ("EnvironmentalParameter", "Environmental Parameter", ["Water parameter"], None),
    ("PhysicoChemParam", "Physicochemical Parameter", [], "EnvironmentalParameter"),
    ("HydrogenIonConc", "Hydrogen Ion Concentration", ["pH"], "PhysicoChemParam"),
    ("OxygenSaturation", "Oxygen Saturation", ["Dissolved oxygen", "DO level"], "PhysicoChemParam"),
    ("BODParameter", "BOD Parameter", ["Biochemical oxygen demand"], "PhysicoChemParam"),
    ("CODParameter", "COD Parameter", ["Chemical oxygen demand"], "PhysicoChemParam"),
    ("TotalSolids", "Total Dissolved Solids", ["TDS"], "PhysicoChemParam"),
    ("WaterAlkalinity", "Water Alkalinity", ["Alkalinity", "Buffering capacity"], "PhysicoChemParam"),
    ("WaterHardness", "Water Hardness", ["Total hardness", "Calcium-magnesium hardness"], "PhysicoChemParam"),
    ("NutrientIndicator", "Nutrient Indicator", ["Nutrient parameter"], "EnvironmentalParameter"),
    ("NitrateNitrogen", "Nitrate-Nitrogen", ["NO3-N", "Nitrate"], "NutrientIndicator"),
    ("NitriteNitrogen", "Nitrite-Nitrogen", ["NO2-N", "Nitrite"], "NutrientIndicator"),
    ("AmmoniacalNitrogen", "Ammoniacal Nitrogen", ["NH3-N", "Ammonia"], "NutrientIndicator"),
    ("TotalKjeldahlN", "Total Kjeldahl Nitrogen", ["TKN", "Total nitrogen"], "NutrientIndicator"),
    ("OrthophosphateP", "Orthophosphate", ["PO4-P", "Phosphate"], "NutrientIndicator"),
    ("TotalP", "Total Phosphorus", ["TP"], "NutrientIndicator"),
    ("BioIndicator", "Biological Indicator", ["Microbiological parameter"], "EnvironmentalParameter"),
    ("ColiformBacteria", "Coliform Bacteria", ["Total coliform"], "BioIndicator"),
    ("ThermotolerantColiform", "Thermotolerant Coliform", ["Faecal coliform", "Fecal coliform"], "BioIndicator"),
    ("EscherichiaColi", "Escherichia coli", ["E. coli"], "BioIndicator"),
    ("IntestinalEnterococci", "Intestinal Enterococci", ["Enterococci"], "BioIndicator"),
    ("PhysicalProperty", "Physical Property", ["Physical parameter"], "EnvironmentalParameter"),
    ("AmbientTemperature", "Ambient Temperature", ["Temperature"], "PhysicalProperty"),
    ("NephelometricTurbidity", "Nephelometric Turbidity", ["Turbidity", "NTU"], "PhysicalProperty"),
    ("ElectricalConductivity", "Electrical Conductivity", ["EC", "Specific conductance"], "PhysicalProperty"),
    # FALSE FRIEND: HydraulicConductivity is a soil/aquifer property, NOT water EC
    ("HydraulicConductivity", "Hydraulic Conductivity", ["Permeability", "K value"], "PhysicalProperty"),
    ("ApparentColor", "Apparent Color", ["Water colour"], "PhysicalProperty"),
    ("StreamDischarge", "Stream Discharge", ["Flow rate", "Volumetric flow"], "PhysicalProperty"),
    ("GaugeHeight", "Gauge Height", ["Water level", "Stage"], "PhysicalProperty"),
    # FALSE FRIEND: SubstrateHardness is a geological property, NOT water hardness
    ("SubstrateHardness", "Substrate Hardness", ["Rock hardness", "Bed hardness"], "PhysicalProperty"),
    ("TraceElement", "Trace Element", ["Heavy metal parameter"], "EnvironmentalParameter"),
    ("PbConcentration", "Lead Concentration", ["Pb"], "TraceElement"),
    ("HgConcentration", "Mercury Concentration", ["Hg"], "TraceElement"),
    ("CdConcentration", "Cadmium Concentration", ["Cd"], "TraceElement"),
    ("AsConcentration", "Arsenic Concentration", ["As"], "TraceElement"),
    ("CrConcentration", "Chromium Concentration", ["Cr"], "TraceElement"),
    ("CuConcentration", "Copper Concentration", ["Cu"], "TraceElement"),
    ("ZnConcentration", "Zinc Concentration", ["Zn"], "TraceElement"),
    # ── Contaminants ──
    ("EnvironmentalContaminant", "Environmental Contaminant", ["Pollutant"], None),
    ("PersistentPollutant", "Persistent Pollutant", ["Persistent contaminant"], "EnvironmentalContaminant"),
    ("HeavyMetalContam", "Heavy Metal Contaminant", ["Toxic metal"], "PersistentPollutant"),
    ("CyanideCompound", "Cyanide Compound", ["Cyanide"], "PersistentPollutant"),
    ("FluorideCompound", "Fluoride Compound", ["Fluoride"], "PersistentPollutant"),
    ("OrganicContam", "Organic Contaminant", [], "EnvironmentalContaminant"),
    ("PesticideResidue", "Pesticide Residue", ["Pesticide"], "OrganicContam"),
    ("HerbicideResidue", "Herbicide Residue", ["Herbicide"], "OrganicContam"),
    ("PharmaceuticalResidue", "Pharmaceutical Residue", ["Drug residue", "Pharmaceutical compound"], "OrganicContam"),
    ("PFASCompound", "PFAS Compound", ["Per- and polyfluoroalkyl substance", "Forever chemical"], "OrganicContam"),
    ("PolychlorinatedBiphenyl", "Polychlorinated Biphenyl", ["PCB"], "OrganicContam"),
    ("PolyaromaticHC", "Polyaromatic Hydrocarbon", ["PAH"], "OrganicContam"),
    ("EmergingContam", "Emerging Contaminant", ["Contaminant of emerging concern", "CEC"], "EnvironmentalContaminant"),
    ("MicroplasticParticle", "Microplastic Particle", ["Microplastic"], "EmergingContam"),
    ("EndocrineDisruptingChem", "Endocrine Disrupting Chemical", ["EDC", "Endocrine disruptor"], "EmergingContam"),
    ("AMRDeterminant", "Antimicrobial Resistance Determinant", ["ARG", "AMR gene"], "EmergingContam"),
    # ── Instruments ──
    ("ObservationInstrument", "Observation Instrument", ["Monitoring equipment"], None),
    ("InSituProbe", "In-situ Probe", ["Sensor", "Field probe"], "ObservationInstrument"),
    ("pHProbe", "pH Probe", ["pH sensor", "pH meter"], "InSituProbe"),
    ("OxygenProbe", "Oxygen Probe", ["DO sensor", "Dissolved oxygen sensor"], "InSituProbe"),
    ("TurbidityProbe", "Turbidity Probe", ["Nephelometric sensor"], "InSituProbe"),
    ("ConductivityProbe", "Conductivity Probe", ["EC sensor"], "InSituProbe"),
    ("MultiSensorSonde", "Multi-sensor Sonde", ["Multiparameter probe"], "InSituProbe"),
    ("WaterSampler", "Water Sampler", ["Sampling device"], "ObservationInstrument"),
    ("DiscreteSampler", "Discrete Sampler", ["Grab sampler", "Manual sampler"], "WaterSampler"),
    ("TimeIntegratedSampler", "Time-integrated Sampler", ["Automatic sampler", "Auto-sampler"], "WaterSampler"),
    ("DiffusiveGradientSampler", "Diffusive Gradient Sampler", ["Passive sampler", "DGT"], "WaterSampler"),
    ("HydrologicalInstrument", "Hydrological Instrument", ["Field instrument"], "ObservationInstrument"),
    ("CurrentMeter", "Current Meter", ["Flow meter", "Velocity meter"], "HydrologicalInstrument"),
    ("StaffGauge", "Staff Gauge", ["Depth gauge", "Water level gauge"], "HydrologicalInstrument"),
    ("PressureTransducer", "Pressure Transducer", ["Level logger"], "HydrologicalInstrument"),
    # ── Observation Sites ──
    ("ObservationSite", "Observation Site", ["Monitoring station"], None),
    ("PermanentSite", "Permanent Site", ["Fixed station"], "ObservationSite"),
    ("RiversideStation", "Riverside Station", ["Riverbank station"], "PermanentSite"),
    ("LakesideStation", "Lakeside Station", ["Lakeshore station"], "PermanentSite"),
    ("EffluentMonitoringPoint", "Effluent Monitoring Point", ["Outfall station", "Discharge monitoring point"], "PermanentSite"),
    ("TemporaryDeployment", "Temporary Deployment", ["Mobile unit"], "ObservationSite"),
    ("VesselPlatform", "Vessel-based Platform", ["Boat unit", "Ship-based station"], "TemporaryDeployment"),
    ("UAVPlatform", "UAV Platform", ["Drone unit", "Unmanned aerial platform"], "TemporaryDeployment"),
    # ── Programs ──
    ("MonitoringProgram", "Monitoring Program", ["Surveillance program", "Sampling program"], None),
    ("PeriodicSurveillance", "Periodic Surveillance", ["Routine monitoring"], "MonitoringProgram"),
    ("StormEventSampling", "Storm Event Sampling", ["Event-based sampling"], "MonitoringProgram"),
    ("ReferenceConditionSurvey", "Reference Condition Survey", ["Baseline survey"], "MonitoringProgram"),
    ("IncidentResponse", "Incident Response", ["Emergency response"], "MonitoringProgram"),
    # ── Standards ──
    ("QualityStandard", "Quality Standard", ["Environmental standard"], None),
    ("PotableWaterCriterion", "Potable Water Criterion", ["Drinking water standard"], "QualityStandard"),
    ("EcosystemObjective", "Aquatic Ecosystem Objective", ["Aquatic life standard"], "QualityStandard"),
    ("BathingWaterDirective", "Bathing Water Directive", ["Recreational standard"], "QualityStandard"),
    ("IrrigationGuideline", "Irrigation Guideline", ["Irrigation standard"], "QualityStandard"),
    ("DischargePermitLimit", "Discharge Permit Limit", ["Effluent standard"], "QualityStandard"),
    # ── Catchment ──
    ("CatchmentArea", "Catchment Area", ["Watershed", "Drainage area"], None),
    ("DrainageBasin", "Drainage Basin", ["River basin", "Main catchment"], "CatchmentArea"),
    ("SubCatchment", "Sub-Catchment", ["Sub-basin"], "CatchmentArea"),
    ("MicroCatchment", "Micro-Catchment", ["Headwater catchment"], "CatchmentArea"),
    # ── Land Cover ──
    ("LandCoverType", "Land Cover Type", [], None),
    ("UrbanSurface", "Urban Surface", ["Urban area", "Built-up area"], "LandCoverType"),
    ("CroplandArea", "Cropland", ["Agricultural land", "Farmland"], "LandCoverType"),
    ("WoodlandArea", "Woodland", ["Forest land", "Forested area"], "LandCoverType"),
    ("IndustrialSite", "Industrial Site", ["Industrial area"], "LandCoverType"),
    ("NaturalWetland", "Natural Wetland", ["Marsh", "Bog"], "LandCoverType"),
    # ── Pollution Pathways ──
    ("PollutionPathway", "Pollution Pathway", ["Contamination source"], None),
    ("DirectEmission", "Direct Emission", ["Point source"], "PollutionPathway"),
    ("IndustrialEffluent", "Industrial Effluent", ["Factory discharge", "Industrial discharge"], "DirectEmission"),
    ("SewageTreatmentEffluent", "Sewage Treatment Effluent", ["Municipal wastewater"], "DirectEmission"),
    ("StormDrainOutfall", "Storm Drain Outfall", ["Stormwater outfall"], "DirectEmission"),
    ("DiffuseContamination", "Diffuse Contamination", ["Non-point source", "Diffuse source"], "PollutionPathway"),
    ("AgriculturalLeaching", "Agricultural Leaching", ["Agricultural runoff", "Farm runoff"], "DiffuseContamination"),
    ("UrbanSurfaceRunoff", "Urban Surface Runoff", ["Urban runoff"], "DiffuseContamination"),
    ("WetDeposition", "Wet Deposition", ["Atmospheric deposition", "Acid rain"], "DiffuseContamination"),
    # ── Treatment ──
    ("WaterTreatmentProcess", "Water Treatment Process", ["Treatment"], None),
    ("MechanicalFiltration", "Mechanical Filtration", ["Filtration"], "WaterTreatmentProcess"),
    ("ChemicalDisinfection", "Chemical Disinfection", ["Chlorination", "Chlorine treatment"], "WaterTreatmentProcess"),
    ("UltravioletTreatment", "Ultraviolet Treatment", ["UV disinfection"], "WaterTreatmentProcess"),
    ("MembraneTreatment", "Membrane Treatment", ["Reverse osmosis", "RO treatment"], "WaterTreatmentProcess"),
    ("AdsorptionTreatment", "Adsorption Treatment", ["Activated carbon", "GAC treatment"], "WaterTreatmentProcess"),
    # ── Ecological ──
    ("AquaticHabitat", "Aquatic Habitat", ["Aquatic ecosystem"], None),
    ("LenticHabitat", "Lentic Habitat", ["Standing water habitat", "Lentic ecosystem"], "AquaticHabitat"),
    ("LoticHabitat", "Lotic Habitat", ["Flowing water habitat", "Lotic ecosystem"], "AquaticHabitat"),
    ("RiparianHabitat", "Riparian Habitat", ["Riparian zone", "Streamside habitat"], "AquaticHabitat"),
    # ── Biological ──
    ("BiologicalQualityElement", "Biological Quality Element", ["Biological indicator"], None),
    ("BenthicInvertebrate", "Benthic Invertebrate", ["Macroinvertebrate", "Benthic fauna"], "BiologicalQualityElement"),
    ("PhytoplanktonCommunity", "Phytoplankton Community", ["Phytoplankton", "Algal assemblage"], "BiologicalQualityElement"),
    ("BenthicDiatom", "Benthic Diatom", ["Periphyton", "Attached algae"], "BiologicalQualityElement"),
    ("AquaticMacrophyte", "Aquatic Macrophyte", ["Water plant"], "BiologicalQualityElement"),
    # ── Sediment ──
    ("SedimentType", "Sediment Type", [], None),
    ("BedMaterial", "Bed Material", ["Bed sediment", "Bottom sediment"], "SedimentType"),
    ("SuspendedMatter", "Suspended Matter", ["Suspended sediment", "TSS"], "SedimentType"),
    # ── Geomorphology ──
    ("GeomorphicFeature", "Geomorphic Feature", [], None),
    ("FloodplainArea", "Floodplain", ["Flood plain", "Alluvial plain"], "GeomorphicFeature"),
    ("ChannelMorphology", "Channel Morphology", ["Stream channel"], "GeomorphicFeature"),
    ("RiverDelta", "River Delta", ["Delta"], "GeomorphicFeature"),
    # ── Hydrology ──
    ("HydrologicProcess", "Hydrologic Process", ["Hydrological process"], None),
    ("EvaporativeProcess", "Evaporative Process", ["Evaporation", "Evapotranspiration"], "HydrologicProcess"),
    ("PrecipitationEvent", "Precipitation Event", ["Rainfall", "Precipitation"], "HydrologicProcess"),
    ("InfiltrationProcess", "Infiltration Process", ["Infiltration", "Percolation"], "HydrologicProcess"),
    ("OverlandFlow", "Overland Flow", ["Surface runoff"], "HydrologicProcess"),
    ("BaseflowContribution", "Baseflow Contribution", ["Baseflow", "Groundwater discharge"], "HydrologicProcess"),
    # ── Seasonal ──
    ("HydrologicEvent", "Hydrologic Event", [], None),
    # FALSE FRIEND: "Spring Freshet" shares "Spring" with groundwater spring
    ("SpringFreshet", "Spring Freshet", ["Snowmelt flood", "Spring flood"], "HydrologicEvent"),
    ("LowFlowPeriod", "Low Flow Period", ["Summer low flow", "Drought"], "HydrologicEvent"),
]

# Restriction-defined classes for target
TARGET_DEFINED_CLASSES = [
    ("DegradedRiver", "Degraded River",
     "RiverSystem AND hasEcologicalStatus value 'poor'", "RiverSystem"),
    ("HypereutrophicLake", "Hypereutrophic Lake",
     "NaturalLake AND hasTrophicState value 'hypereutrophic'", "NaturalLake"),
    ("CompliantSource", "Compliant Water Source",
     "HydrologicalFeature AND conformsWith some PotableWaterCriterion", "HydrologicalFeature"),
    ("ContaminatedFormation", "Contaminated Formation",
     "SubsurfaceWater AND affectedBy some HeavyMetalContam", "SubsurfaceWater"),
    ("InstrumentedRiver", "Instrumented River",
     "RiverSystem AND monitoredBy some PermanentSite", "RiverSystem"),
    ("UrbanCatchment", "Urban Catchment",
     "CatchmentArea AND hasPrimaryLandCover some UrbanSurface", "CatchmentArea"),
    ("AcidStressedWater", "Acid-stressed Water Body",
     "HydrologicalFeature AND hasPH value 'acidic'", "HydrologicalFeature"),
    ("ThermallySensitive", "Thermally Sensitive Water Body",
     "HydrologicalFeature AND hasThermalRegime value 'sensitive'", "HydrologicalFeature"),
]

# Target object properties
TARGET_PROPERTIES = [
    ("observesParameter", "observes parameter", ["measures"], "HydrologicalFeature", "EnvironmentalParameter"),
    ("monitoredBy", "monitored by", ["observed by"], "HydrologicalFeature", "ObservationSite"),
    ("withinCatchment", "within catchment", ["in watershed"], "HydrologicalFeature", "CatchmentArea"),
    ("affectedBy", "affected by", ["contaminated by"], "HydrologicalFeature", "EnvironmentalContaminant"),
    ("conformsWith", "conforms with", ["meets standard"], "HydrologicalFeature", "QualityStandard"),
    ("impactedBy", "impacted by", ["pollution source"], "HydrologicalFeature", "PollutionPathway"),
    ("undergoesTreatment", "undergoes treatment", ["treated by"], "HydrologicalFeature", "WaterTreatmentProcess"),
    ("sampledWith", "sampled with", ["collected using"], "MonitoringProgram", "WaterSampler"),
    ("receivesInflow", "receives inflow", ["has upstream"], "HydrologicalFeature", "HydrologicalFeature"),
    ("tributaryOf", "tributary of", ["flows into"], "HydrologicalFeature", "HydrologicalFeature"),
    ("hasLandCover", "has land cover", ["land use"], "CatchmentArea", "LandCoverType"),
    ("supportsHabitat", "supports habitat", ["has ecosystem"], "HydrologicalFeature", "AquaticHabitat"),
    ("hasQualityStatus", "has quality status", [], "HydrologicalFeature", "QualityStandard"),
    ("hasFlowRegime", "has flow regime", [], "HydrologicalFeature", "HydrologicProcess"),
]


def generate_owl(filepath, base_uri, ontology_uri, classes, defined_classes, properties):
    """Generate an OWL/RDF-XML ontology file with restrictions and properties."""
    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<rdf:RDF xmlns="{ns}"'.format(ns=base_uri + "#"))
    lines.append('     xml:base="{ns}"'.format(ns=base_uri))
    lines.append('     xmlns:owl="http://www.w3.org/2002/07/owl#"')
    lines.append('     xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"')
    lines.append('     xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"')
    lines.append('     xmlns:skos="http://www.w3.org/2004/02/skos/core#"')
    lines.append('     xmlns:xsd="http://www.w3.org/2001/XMLSchema#">')
    lines.append('')
    lines.append('  <owl:Ontology rdf:about="{uri}"/>'.format(uri=ontology_uri))
    lines.append('')

    # Generate object properties
    for prop_id, label, alt_labels, domain_id, range_id in properties:
        lines.append('  <owl:ObjectProperty rdf:about="{ns}#{pid}">'.format(
            ns=base_uri, pid=prop_id))
        lines.append('    <rdfs:label>{lbl}</rdfs:label>'.format(lbl=escape(label)))
        for alt in alt_labels:
            lines.append('    <skos:altLabel>{alt}</skos:altLabel>'.format(alt=escape(alt)))
        lines.append('    <rdfs:domain rdf:resource="{ns}#{did}"/>'.format(
            ns=base_uri, did=domain_id))
        lines.append('    <rdfs:range rdf:resource="{ns}#{rid}"/>'.format(
            ns=base_uri, rid=range_id))
        lines.append('  </owl:ObjectProperty>')
        lines.append('')

    # Generate regular classes
    for cls_id, label, alt_labels, parent_id in classes:
        lines.append('  <owl:Class rdf:about="{ns}#{cid}">'.format(ns=base_uri, cid=cls_id))
        lines.append('    <rdfs:label>{lbl}</rdfs:label>'.format(lbl=escape(label)))
        for alt in alt_labels:
            lines.append('    <skos:altLabel>{alt}</skos:altLabel>'.format(alt=escape(alt)))
        if parent_id:
            lines.append('    <rdfs:subClassOf rdf:resource="{ns}#{pid}"/>'.format(
                ns=base_uri, pid=parent_id))
        lines.append('  </owl:Class>')
        lines.append('')

    # Generate restriction-defined classes
    for cls_id, label, equiv_desc, parent_id in defined_classes:
        lines.append('  <owl:Class rdf:about="{ns}#{cid}">'.format(ns=base_uri, cid=cls_id))
        lines.append('    <rdfs:label>{lbl}</rdfs:label>'.format(lbl=escape(label)))
        lines.append('    <skos:definition>{desc}</skos:definition>'.format(
            desc=escape(equiv_desc)))
        if parent_id:
            lines.append('    <rdfs:subClassOf rdf:resource="{ns}#{pid}"/>'.format(
                ns=base_uri, pid=parent_id))

        # Parse and emit a simplified OWL restriction as equivalentClass
        # Format: "BaseClass AND property value/some 'val'/ClassName"
        parts = equiv_desc.split(" AND ", 1)
        if len(parts) == 2:
            base_cls = parts[0].strip()
            restriction_part = parts[1].strip()
            lines.append('    <owl:equivalentClass>')
            lines.append('      <owl:Class>')
            lines.append('        <owl:intersectionOf rdf:parseType="Collection">')
            lines.append('          <owl:Class rdf:about="{ns}#{bc}"/>'.format(
                ns=base_uri, bc=base_cls))

            if " some " in restriction_part:
                prop_name, filler = restriction_part.split(" some ", 1)
                prop_name = prop_name.strip()
                filler = filler.strip()
                lines.append('          <owl:Restriction>')
                lines.append('            <owl:onProperty rdf:resource="{ns}#{pn}"/>'.format(
                    ns=base_uri, pn=prop_name))
                lines.append('            <owl:someValuesFrom rdf:resource="{ns}#{f}"/>'.format(
                    ns=base_uri, f=filler))
                lines.append('          </owl:Restriction>')
            elif " value " in restriction_part:
                prop_name, val = restriction_part.split(" value ", 1)
                prop_name = prop_name.strip()
                val = val.strip().strip("'\"")
                lines.append('          <owl:Restriction>')
                lines.append('            <owl:onProperty rdf:resource="{ns}#{pn}"/>'.format(
                    ns=base_uri, pn=prop_name))
                lines.append('            <owl:hasValue>{v}</owl:hasValue>'.format(v=escape(val)))
                lines.append('          </owl:Restriction>')

            lines.append('        </owl:intersectionOf>')
            lines.append('      </owl:Class>')
            lines.append('    </owl:equivalentClass>')

        lines.append('  </owl:Class>')
        lines.append('')

    lines.append('</rdf:RDF>')
    lines.append('')

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def generate_example_alignment(filepath):
    """Generate a small example alignment showing the expected output format."""
    content = '''<?xml version="1.0" encoding="utf-8"?>
<rdf:RDF xmlns="http://knowledgeweb.semanticweb.org/heterogeneity/alignment"
     xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
     xmlns:xsd="http://www.w3.org/2001/XMLSchema#">

<Alignment>
<xml>yes</xml>
<level>0</level>
<type>??</type>
<onto1>
  <Ontology rdf:about="http://wqmo.owl">
    <location>file:///app/data/source.owl</location>
  </Ontology>
</onto1>
<onto2>
  <Ontology rdf:about="http://hro.owl">
    <location>file:///app/data/target.owl</location>
  </Ontology>
</onto2>

<!-- Class equivalence: same label -->
<map>
  <Cell>
    <entity1 rdf:resource="http://wqmo.owl#River"/>
    <entity2 rdf:resource="http://hro.owl#RiverSystem"/>
    <measure rdf:datatype="xsd:float">1.0</measure>
    <relation>=</relation>
  </Cell>
</map>

<!-- Property equivalence -->
<map>
  <Cell>
    <entity1 rdf:resource="http://wqmo.owl#hasMeasurement"/>
    <entity2 rdf:resource="http://hro.owl#observesParameter"/>
    <measure rdf:datatype="xsd:float">0.85</measure>
    <relation>=</relation>
  </Cell>
</map>

<!-- Subsumption: source is narrower than target -->
<map>
  <Cell>
    <entity1 rdf:resource="http://wqmo.owl#SurfaceWater"/>
    <entity2 rdf:resource="http://hro.owl#HydrologicalFeature"/>
    <measure rdf:datatype="xsd:float">0.8</measure>
    <relation>&lt;</relation>
  </Cell>
</map>

</Alignment>
</rdf:RDF>
'''
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)


def generate_readme(filepath):
    """Generate README with task specification."""
    content = """# Hydrological Ontology Alignment Task

## Input Data

- `source.owl` — Water Quality Monitoring Ontology (WQMO) in OWL/RDF-XML (~145 classes, 12 object properties)
- `target.owl` — Hydrological Resource Ontology (HRO) in OWL/RDF-XML (~160 classes, 14 object properties)
- `example_alignment.rdf` — Example showing the expected output format (3 sample correspondences)

## Ontology Structure

Both ontologies model overlapping water-resource and environmental-monitoring domains
but from different perspectives and using different naming conventions.

### Class Features
- `rdfs:label` — Primary human-readable label
- `skos:altLabel` — Zero or more synonyms / alternative labels
- `rdfs:subClassOf` — Hierarchical parent
- `owl:equivalentClass` — Some classes are DEFINED using OWL restrictions
  (intersections with `owl:someValuesFrom` / `owl:hasValue`). These encode
  class semantics beyond what the label conveys.
- `skos:definition` — Natural-language description of restriction-defined classes

### Object Properties
- `rdfs:label` and `skos:altLabel` on properties
- `rdfs:domain` and `rdfs:range` constrain which classes they relate

## Key Challenges

1. **Label matching**: Many classes share labels or alt-labels across ontologies (trivial matches)
2. **Synonym cross-referencing**: Some equivalences require matching source primary label to target alt-label or vice versa
3. **Restriction-defined classes**: Some classes are defined via OWL restrictions and match despite having different labels — the restriction axioms reveal the correspondence
4. **False friends**: Some classes share label tokens but represent different concepts (e.g., "Conductivity" = water EC vs. "Hydraulic Conductivity" = soil permeability; "Spring" = water source vs. "Spring Freshet" = seasonal flood)
5. **Property alignment**: Object properties must be matched using labels and domain/range analysis
6. **Subsumption detection**: Some source classes are broader/narrower than target classes
7. **Structural coherence**: Valid alignments should preserve hierarchical relationships

## Output Format

Produce an alignment file in OAEI alignment XML format. See `example_alignment.rdf`.
Include both class and property correspondences. Use relation types:
- `=` for equivalence
- `>` for source broader than target
- `<` for source narrower than target
"""
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)


if __name__ == '__main__':
    generate_owl(
        '/app/data/source.owl',
        'http://wqmo.owl',
        'http://wqmo.owl',
        SOURCE_CLASSES,
        SOURCE_DEFINED_CLASSES,
        SOURCE_PROPERTIES,
    )
    generate_owl(
        '/app/data/target.owl',
        'http://hro.owl',
        'http://hro.owl',
        TARGET_CLASSES,
        TARGET_DEFINED_CLASSES,
        TARGET_PROPERTIES,
    )
    generate_example_alignment('/app/data/example_alignment.rdf')
    generate_readme('/app/data/README.md')
    os.makedirs('/app/output', exist_ok=True)
    sc = len(SOURCE_CLASSES) + len(SOURCE_DEFINED_CLASSES)
    tc = len(TARGET_CLASSES) + len(TARGET_DEFINED_CLASSES)
    print(f"Data generation complete.")
    print(f"  Source ontology: {sc} classes, {len(SOURCE_PROPERTIES)} properties")
    print(f"  Target ontology: {tc} classes, {len(TARGET_PROPERTIES)} properties")
