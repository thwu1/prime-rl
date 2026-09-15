"""Tests for hydrological ontology alignment output.

"""
import os
import xml.etree.ElementTree as ET
import pytest

ALIGNMENT_PATH = "/app/output/alignment.rdf"
SOURCE_NS = "http://wqmo.owl#"
TARGET_NS = "http://hro.owl#"

# ── Gold standard: class correspondences ─────────────────────────────────
# (source_local_id, target_local_id, relation)

# Trivial equivalences: labels match after normalization or via obvious substring
TRIVIAL_EQUIVALENCES = [
    ("River", "RiverSystem", "="),
    ("Lake", "NaturalLake", "="),
    ("Reservoir", "ArtificialReservoir", "="),
    ("Stream", "StreamSystem", "="),
    ("Wetland", "MarshWetland", "="),
    ("Estuary", "EstuarineZone", "="),
    ("Pond", "NaturalPond", "="),
    ("Creek", "CreekSystem", "="),
    ("Well", "WaterWell", "="),
    ("Spring", "NaturalSpring", "="),
    ("Bay", "BayArea", "="),
    ("Lagoon", "CoastalLagoon", "="),
    ("pH", "HydrogenIonConc", "="),
    ("DissolvedOxygen", "OxygenSaturation", "="),
    ("BOD", "BODParameter", "="),
    ("COD", "CODParameter", "="),
    ("TotalDissolvedSolids", "TotalSolids", "="),
    ("Alkalinity", "WaterAlkalinity", "="),
    ("Hardness", "WaterHardness", "="),
    ("Nitrate", "NitrateNitrogen", "="),
    ("Nitrite", "NitriteNitrogen", "="),
    ("Ammonia", "AmmoniacalNitrogen", "="),
    ("TotalNitrogen", "TotalKjeldahlN", "="),
    ("Phosphate", "OrthophosphateP", "="),
    ("TotalPhosphorus", "TotalP", "="),
    ("TotalColiform", "ColiformBacteria", "="),
    ("FecalColiform", "ThermotolerantColiform", "="),
    ("EColi", "EscherichiaColi", "="),
    ("Enterococci", "IntestinalEnterococci", "="),
    ("Turbidity", "NephelometricTurbidity", "="),
    ("WaterColor", "ApparentColor", "="),
    ("FlowRate", "StreamDischarge", "="),
    ("WaterLevel", "GaugeHeight", "="),
    ("LeadConc", "PbConcentration", "="),
    ("MercuryConc", "HgConcentration", "="),
    ("CadmiumConc", "CdConcentration", "="),
    ("ArsenicConc", "AsConcentration", "="),
    ("ChromiumConc", "CrConcentration", "="),
    ("CopperConc", "CuConcentration", "="),
    ("ZincConc", "ZnConcentration", "="),
    ("HeavyMetal", "HeavyMetalContam", "="),
    ("CyanideContam", "CyanideCompound", "="),
    ("FluorideContam", "FluorideCompound", "="),
    ("Pesticide", "PesticideResidue", "="),
    ("Herbicide", "HerbicideResidue", "="),
    ("PFAS", "PFASCompound", "="),
    ("PCB", "PolychlorinatedBiphenyl", "="),
    ("PAH", "PolyaromaticHC", "="),
    ("Microplastic", "MicroplasticParticle", "="),
    ("AMRGene", "AMRDeterminant", "="),
    ("pHSensor", "pHProbe", "="),
    ("DOSensor", "OxygenProbe", "="),
    ("TurbiditySensor", "TurbidityProbe", "="),
    ("ConductivitySensor", "ConductivityProbe", "="),
    ("GrabSampler", "DiscreteSampler", "="),
    ("FlowMeter", "CurrentMeter", "="),
    ("DepthGauge", "StaffGauge", "="),
    ("RiverbankStation", "RiversideStation", "="),
    ("LakeshoreStation", "LakesideStation", "="),
    ("OutfallStation", "EffluentMonitoringPoint", "="),
    ("BoatUnit", "VesselPlatform", "="),
    ("DroneUnit", "UAVPlatform", "="),
    ("DrinkingWaterStandard", "PotableWaterCriterion", "="),
    ("RecreationalStandard", "BathingWaterDirective", "="),
    ("IrrigationStandard", "IrrigationGuideline", "="),
    ("EffluentStandard", "DischargePermitLimit", "="),
    ("IndustrialDischarge", "IndustrialEffluent", "="),
    ("MunicipalWastewater", "SewageTreatmentEffluent", "="),
    ("StormwaterOutfall", "StormDrainOutfall", "="),
    ("AgriculturalRunoff", "AgriculturalLeaching", "="),
    ("UrbanRunoff", "UrbanSurfaceRunoff", "="),
    ("AtmosphericDeposition", "WetDeposition", "="),
    ("Filtration", "MechanicalFiltration", "="),
    ("Chlorination", "ChemicalDisinfection", "="),
    ("UVDisinfection", "UltravioletTreatment", "="),
    ("ReverseOsmosis", "MembraneTreatment", "="),
    ("ActivatedCarbon", "AdsorptionTreatment", "="),
    ("Macroinvertebrate", "BenthicInvertebrate", "="),
    ("Phytoplankton", "PhytoplanktonCommunity", "="),
    ("Periphyton", "BenthicDiatom", "="),
    ("BedSediment", "BedMaterial", "="),
    ("SuspendedSediment", "SuspendedMatter", "="),
    ("Floodplain", "FloodplainArea", "="),
    ("Delta", "RiverDelta", "="),
    ("Evaporation", "EvaporativeProcess", "="),
    ("Precipitation", "PrecipitationEvent", "="),
    ("Infiltration", "InfiltrationProcess", "="),
    ("Baseflow", "BaseflowContribution", "="),
    ("SpringFlood", "SpringFreshet", "="),
    ("SummerLowFlow", "LowFlowPeriod", "="),
    ("Sediment", "SedimentType", "="),
]

# Non-trivial equivalences: require alt-label, restriction, or structural matching
NONTRIVIAL_EQUIVALENCES = [
    # Alt-label cross-references (primary labels differ)
    ("Groundwater", "SubsurfaceWater", "="),
    ("UnconfinedAquifer", "UnconfinedFormation", "="),
    ("ConfinedAquifer", "ConfinedFormation", "="),
    ("Canal", "IrrigationCanal", "="),
    ("WaterQualityParameter", "EnvironmentalParameter", "="),
    ("ChemicalParameter", "PhysicoChemParam", "="),
    ("NutrientParameter", "NutrientIndicator", "="),
    ("MicrobialParameter", "BioIndicator", "="),
    ("PhysicalParameter", "PhysicalProperty", "="),
    ("MetalParameter", "TraceElement", "="),
    ("Contaminant", "EnvironmentalContaminant", "="),
    ("InorganicContaminant", "PersistentPollutant", "="),
    ("OrganicContaminant", "OrganicContam", "="),
    ("EmergingContaminant", "EmergingContam", "="),
    ("PharmaceuticalCompound", "PharmaceuticalResidue", "="),
    ("EndocrineDisruptor", "EndocrineDisruptingChem", "="),
    ("Conductivity", "ElectricalConductivity", "="),
    ("WaterTemperature", "AmbientTemperature", "="),
    ("MonitoringEquipment", "ObservationInstrument", "="),
    ("Sensor", "InSituProbe", "="),
    ("MultiparameterProbe", "MultiSensorSonde", "="),
    ("SamplingDevice", "WaterSampler", "="),
    ("AutoSampler", "TimeIntegratedSampler", "="),
    ("PassiveSampler", "DiffusiveGradientSampler", "="),
    ("FieldInstrument", "HydrologicalInstrument", "="),
    ("MonitoringStation", "ObservationSite", "="),
    ("FixedStation", "PermanentSite", "="),
    ("MobileUnit", "TemporaryDeployment", "="),
    ("SamplingProgram", "MonitoringProgram", "="),
    ("RoutineMonitoring", "PeriodicSurveillance", "="),
    ("EventSampling", "StormEventSampling", "="),
    ("BaselineSurvey", "ReferenceConditionSurvey", "="),
    ("EmergencyResponse", "IncidentResponse", "="),
    ("WaterQualityStandard", "QualityStandard", "="),
    ("AquaticLifeStandard", "EcosystemObjective", "="),
    ("Watershed", "CatchmentArea", "="),
    ("RiverBasin", "DrainageBasin", "="),
    ("SubBasin", "SubCatchment", "="),
    ("UrbanArea", "UrbanSurface", "="),
    ("AgriculturalLand", "CroplandArea", "="),
    ("ForestLand", "WoodlandArea", "="),
    ("IndustrialArea", "IndustrialSite", "="),
    ("WetlandUse", "NaturalWetland", "="),
    ("PollutionSource", "PollutionPathway", "="),
    ("PointSource", "DirectEmission", "="),
    ("DiffuseSource", "DiffuseContamination", "="),
    ("TreatmentProcess", "WaterTreatmentProcess", "="),
    ("AquaticEcosystem", "AquaticHabitat", "="),
    ("LenticEcosystem", "LenticHabitat", "="),
    ("LoticEcosystem", "LoticHabitat", "="),
    ("RiparianZone", "RiparianHabitat", "="),
    ("SurfaceRunoff", "OverlandFlow", "="),
    # Restriction-defined class matches
    ("PollutedRiver", "DegradedRiver", "="),
    ("EutrophicLake", "HypereutrophicLake", "="),
    ("PotableSource", "CompliantSource", "="),
    ("ContaminatedAquifer", "ContaminatedFormation", "="),
    ("MonitoredRiver", "InstrumentedRiver", "="),
    ("UrbanizedCatchment", "UrbanCatchment", "="),
    ("AcidifiedWater", "AcidStressedWater", "="),
    ("ThermallyStressed", "ThermallySensitive", "="),
]

# Subsumption correspondences
SUBSUMPTIONS = [
    ("SurfaceWater", "HydrologicalFeature", "<"),
    ("CoastalWater", "TransitionalWater", "<"),
    ("LandUseType", "LandCoverType", "<"),
    ("RiverChannel", "ChannelMorphology", "<"),
    ("GeomorphFeature", "GeomorphicFeature", "<"),
    ("HydrologicalProcess", "HydrologicProcess", "<"),
    ("SeasonalEvent", "HydrologicEvent", "<"),
    ("BiologicalIndicator", "BiologicalQualityElement", "<"),
]

# Property correspondences
PROPERTY_GOLD = [
    ("hasMeasurement", "observesParameter", "="),
    ("monitoredAt", "monitoredBy", "="),
    ("locatedIn", "withinCatchment", "="),
    ("hasContaminant", "affectedBy", "="),
    ("meetsStandard", "conformsWith", "="),
    ("receivesFrom", "impactedBy", "="),
    ("treatedBy", "undergoesTreatment", "="),
    ("sampledUsing", "sampledWith", "="),
    ("flowsInto", "tributaryOf", "="),
    ("hasLandUse", "hasLandCover", "="),
    ("hasEcosystem", "supportsHabitat", "="),
    ("hasUpstream", "receivesInflow", "="),
]

# False-friend pairs: classes that share label tokens but are semantically
# different. A correct alignment must NOT include these pairs.
FALSE_FRIENDS = [
    ("Conductivity", "HydraulicConductivity"),
    ("Hardness", "SubstrateHardness"),
    ("Spring", "SpringFreshet"),
    ("RiverChannel", "Channel"),
    ("IndustrialDischarge", "StreamDischarge"),
    ("WetlandUse", "MarshWetland"),
    ("BiologicalIndicator", "BioIndicator"),
]

# ── Build evaluation sets ────────────────────────────────────────────────
GOLD_CLASS = TRIVIAL_EQUIVALENCES + NONTRIVIAL_EQUIVALENCES + SUBSUMPTIONS
GOLD_CLASS_SET = {(SOURCE_NS + s, TARGET_NS + t, r) for s, t, r in GOLD_CLASS}
GOLD_CLASS_PAIRS = {(SOURCE_NS + s, TARGET_NS + t) for s, t, r in GOLD_CLASS}

NONTRIVIAL_SET = {(SOURCE_NS + s, TARGET_NS + t) for s, t, r in NONTRIVIAL_EQUIVALENCES}

PROPERTY_SET = {(SOURCE_NS + s, TARGET_NS + t) for s, t, r in PROPERTY_GOLD}

FALSE_FRIEND_PAIRS = {(SOURCE_NS + s, TARGET_NS + t) for s, t in FALSE_FRIENDS}

# Hierarchy for structural coherence check (source parent -> child)
SOURCE_HIERARCHY = {
    "SurfaceWater": "WaterBody", "River": "SurfaceWater", "Lake": "SurfaceWater",
    "Reservoir": "SurfaceWater", "Stream": "SurfaceWater", "Wetland": "SurfaceWater",
    "Estuary": "SurfaceWater", "Canal": "SurfaceWater", "Pond": "SurfaceWater",
    "Creek": "SurfaceWater", "Groundwater": "WaterBody", "Aquifer": "Groundwater",
    "UnconfinedAquifer": "Aquifer", "ConfinedAquifer": "Aquifer", "Well": "Groundwater",
    "Spring": "Groundwater", "CoastalWater": "WaterBody", "Bay": "CoastalWater",
    "Lagoon": "CoastalWater",
    "ChemicalParameter": "WaterQualityParameter", "NutrientParameter": "WaterQualityParameter",
    "MicrobialParameter": "WaterQualityParameter", "PhysicalParameter": "WaterQualityParameter",
    "MetalParameter": "WaterQualityParameter",
    "InorganicContaminant": "Contaminant", "OrganicContaminant": "Contaminant",
    "EmergingContaminant": "Contaminant",
    "Sensor": "MonitoringEquipment", "SamplingDevice": "MonitoringEquipment",
    "FieldInstrument": "MonitoringEquipment",
    "FixedStation": "MonitoringStation", "MobileUnit": "MonitoringStation",
    "PointSource": "PollutionSource", "DiffuseSource": "PollutionSource",
    "LenticEcosystem": "AquaticEcosystem", "LoticEcosystem": "AquaticEcosystem",
    "RiparianZone": "AquaticEcosystem",
}

TARGET_HIERARCHY = {
    "FlowingWater": "HydrologicalFeature", "StandingWater": "HydrologicalFeature",
    "TransitionalWater": "HydrologicalFeature", "SubsurfaceWater": "HydrologicalFeature",
    "IrrigationCanal": "HydrologicalFeature",
    "RiverSystem": "FlowingWater", "StreamSystem": "FlowingWater",
    "CreekSystem": "FlowingWater", "Channel": "FlowingWater",
    "NaturalLake": "StandingWater", "ArtificialReservoir": "StandingWater",
    "NaturalPond": "StandingWater", "MarshWetland": "StandingWater",
    "EstuarineZone": "TransitionalWater", "CoastalLagoon": "TransitionalWater",
    "BayArea": "TransitionalWater",
    "UnconfinedFormation": "SubsurfaceWater", "ConfinedFormation": "SubsurfaceWater",
    "WaterWell": "SubsurfaceWater", "NaturalSpring": "SubsurfaceWater",
    "PhysicoChemParam": "EnvironmentalParameter", "NutrientIndicator": "EnvironmentalParameter",
    "BioIndicator": "EnvironmentalParameter", "PhysicalProperty": "EnvironmentalParameter",
    "TraceElement": "EnvironmentalParameter",
    "PersistentPollutant": "EnvironmentalContaminant", "OrganicContam": "EnvironmentalContaminant",
    "EmergingContam": "EnvironmentalContaminant",
    "InSituProbe": "ObservationInstrument", "WaterSampler": "ObservationInstrument",
    "HydrologicalInstrument": "ObservationInstrument",
    "PermanentSite": "ObservationSite", "TemporaryDeployment": "ObservationSite",
    "DirectEmission": "PollutionPathway", "DiffuseContamination": "PollutionPathway",
    "LenticHabitat": "AquaticHabitat", "LoticHabitat": "AquaticHabitat",
    "RiparianHabitat": "AquaticHabitat",
}


def get_ancestors(hierarchy, class_id):
    """Get all ancestors of a class in the hierarchy."""
    ancestors = set()
    current = class_id
    while current in hierarchy:
        parent = hierarchy[current]
        ancestors.add(parent)
        current = parent
    return ancestors


def parse_alignment(filepath):
    """Parse an OAEI alignment XML file and return set of (entity1, entity2, relation)."""
    tree = ET.parse(filepath)
    root = tree.getroot()
    ns_rdf = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    correspondences = set()

    for cell in root.iter():
        if cell.tag.endswith("Cell") or cell.tag == "Cell":
            e1, e2, rel = None, None, None
            for child in cell:
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if tag == "entity1":
                    e1 = child.get("{%s}resource" % ns_rdf) or child.get("rdf:resource")
                elif tag == "entity2":
                    e2 = child.get("{%s}resource" % ns_rdf) or child.get("rdf:resource")
                elif tag == "relation":
                    rel = (child.text or "").strip()
            if e1 and e2 and rel:
                rel = rel.replace("&gt;", ">").replace("&lt;", "<").replace("&equiv;", "=")
                if rel in ("equivalence", "Equivalence"):
                    rel = "="
                if rel in ("=", ">", "<"):
                    correspondences.add((e1, e2, rel))

    return correspondences


def split_correspondences(correspondences):
    """Split correspondences into class and property sets based on namespace fragments."""
    class_corrs = set()
    prop_corrs = set()
    # Property IDs in source and target ontologies
    source_prop_ids = {
        "hasMeasurement", "monitoredAt", "locatedIn", "hasContaminant",
        "meetsStandard", "receivesFrom", "treatedBy", "sampledUsing",
        "flowsInto", "hasUpstream", "hasLandUse", "hasEcosystem",
    }
    target_prop_ids = {
        "observesParameter", "monitoredBy", "withinCatchment", "affectedBy",
        "conformsWith", "impactedBy", "undergoesTreatment", "sampledWith",
        "receivesInflow", "tributaryOf", "hasLandCover", "supportsHabitat",
        "hasQualityStatus", "hasFlowRegime",
    }
    for e1, e2, rel in correspondences:
        s_local = e1.split("#")[-1] if "#" in e1 else ""
        t_local = e2.split("#")[-1] if "#" in e2 else ""
        if s_local in source_prop_ids or t_local in target_prop_ids:
            prop_corrs.add((e1, e2, rel))
        else:
            class_corrs.add((e1, e2, rel))
    return class_corrs, prop_corrs


class TestAlignmentExists:
    def test_output_file_exists(self):
        assert os.path.isfile(ALIGNMENT_PATH), (
            f"Output alignment file not found at {ALIGNMENT_PATH}"
        )

    def test_output_is_valid_xml(self):
        try:
            ET.parse(ALIGNMENT_PATH)
        except ET.ParseError as e:
            pytest.fail(f"Output is not valid XML: {e}")

    def test_output_has_correspondences(self):
        correspondences = parse_alignment(ALIGNMENT_PATH)
        assert len(correspondences) > 0, "No correspondences found in alignment output"


class TestAlignmentFormat:
    def test_correspondences_have_valid_uris(self):
        correspondences = parse_alignment(ALIGNMENT_PATH)
        for e1, e2, rel in correspondences:
            assert e1.startswith("http://"), f"entity1 URI invalid: {e1}"
            assert e2.startswith("http://"), f"entity2 URI invalid: {e2}"

    def test_correspondences_reference_correct_ontologies(self):
        correspondences = parse_alignment(ALIGNMENT_PATH)
        source_count = sum(1 for e1, _, _ in correspondences if e1.startswith(SOURCE_NS))
        target_count = sum(1 for _, e2, _ in correspondences if e2.startswith(TARGET_NS))
        assert source_count > 0, "No correspondences reference the source ontology"
        assert target_count > 0, "No correspondences reference the target ontology"

    def test_relations_are_valid(self):
        correspondences = parse_alignment(ALIGNMENT_PATH)
        valid = {"=", ">", "<"}
        for e1, e2, rel in correspondences:
            assert rel in valid, f"Invalid relation type: {rel}"


class TestClassAlignmentQuality:
    @staticmethod
    def _compute_class_metrics():
        all_corrs = parse_alignment(ALIGNMENT_PATH)
        class_corrs, _ = split_correspondences(all_corrs)
        pred_pairs = {(e1, e2) for e1, e2, _ in class_corrs}
        tp = len(pred_pairs & GOLD_CLASS_PAIRS)
        fp = len(pred_pairs - GOLD_CLASS_PAIRS)
        fn = len(GOLD_CLASS_PAIRS - pred_pairs)
        p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * p * r / (p + r)) if (p + r) > 0 else 0.0
        return p, r, f1, tp, fp, fn, pred_pairs

    def test_class_precision(self):
        p, r, f1, tp, fp, fn, _ = self._compute_class_metrics()
        assert p >= 0.72, (
            f"Class precision {p:.4f} < 0.72 (TP={tp}, FP={fp}, FN={fn})"
        )

    def test_class_recall(self):
        p, r, f1, tp, fp, fn, _ = self._compute_class_metrics()
        assert r >= 0.68, (
            f"Class recall {r:.4f} < 0.68 (TP={tp}, FP={fp}, FN={fn}, gold={len(GOLD_CLASS_PAIRS)})"
        )

    def test_class_f1(self):
        p, r, f1, tp, fp, fn, _ = self._compute_class_metrics()
        assert f1 >= 0.70, (
            f"Class F1 {f1:.4f} < 0.70 (precision={p:.4f}, recall={r:.4f})"
        )

    def test_nontrivial_recall(self):
        """Verify the system finds correspondences beyond simple label matching."""
        all_corrs = parse_alignment(ALIGNMENT_PATH)
        class_corrs, _ = split_correspondences(all_corrs)
        pred_pairs = {(e1, e2) for e1, e2, _ in class_corrs}
        nontrivial_found = len(pred_pairs & NONTRIVIAL_SET)
        assert nontrivial_found >= 10, (
            f"Only {nontrivial_found} non-trivial correspondences detected "
            f"(need >= 10 out of {len(NONTRIVIAL_SET)}). "
            f"Label matching alone is insufficient — use skos:altLabel, "
            f"owl:equivalentClass restrictions, and structural analysis."
        )


class TestPropertyAlignment:
    def test_property_correspondences(self):
        """Verify that object property correspondences are detected."""
        all_corrs = parse_alignment(ALIGNMENT_PATH)
        _, prop_corrs = split_correspondences(all_corrs)
        pred_prop_pairs = {(e1, e2) for e1, e2, _ in prop_corrs}
        prop_found = len(pred_prop_pairs & PROPERTY_SET)
        assert prop_found >= 4, (
            f"Only {prop_found} property correspondences detected "
            f"(need >= 4 out of {len(PROPERTY_SET)}). "
            f"Properties must be aligned using label + domain/range analysis."
        )


class TestFalseFriendRejection:
    def test_false_friends_rejected(self):
        """Verify that semantically different classes with similar labels are NOT matched."""
        all_corrs = parse_alignment(ALIGNMENT_PATH)
        class_corrs, _ = split_correspondences(all_corrs)
        pred_pairs = {(e1, e2) for e1, e2, _ in class_corrs}
        ff_accepted = len(pred_pairs & FALSE_FRIEND_PAIRS)
        assert ff_accepted <= 2, (
            f"{ff_accepted} false-friend pairs were incorrectly matched (max 2 allowed). "
            f"False friends are classes sharing label tokens but with different semantics "
            f"(e.g., electrical conductivity vs. hydraulic conductivity). "
            f"Use hierarchical context and domain/range analysis to disambiguate."
        )


class TestStructuralCoherence:
    def test_alignment_preserves_hierarchy(self):
        """Check that matched classes preserve hierarchical relationships.

        If source class B is a subclass of A, and both B and A are matched
        to B' and A' respectively, then B' should be a descendant of A'
        in the target hierarchy.
        """
        all_corrs = parse_alignment(ALIGNMENT_PATH)
        class_corrs, _ = split_correspondences(all_corrs)

        # Build source→target mapping
        s2t = {}
        for e1, e2, rel in class_corrs:
            if rel == "=":
                s_local = e1.replace(SOURCE_NS, "")
                t_local = e2.replace(TARGET_NS, "")
                s2t[s_local] = t_local

        coherent = 0
        total_checked = 0

        for child, parent in SOURCE_HIERARCHY.items():
            if child in s2t and parent in s2t:
                total_checked += 1
                t_child = s2t[child]
                t_parent = s2t[parent]
                # Check if t_child is descendant of t_parent
                t_ancestors = get_ancestors(TARGET_HIERARCHY, t_child)
                if t_parent in t_ancestors or t_child == t_parent:
                    coherent += 1

        if total_checked == 0:
            pytest.skip("Not enough matched hierarchy pairs to evaluate coherence")

        coherence = coherent / total_checked
        assert coherence >= 0.65, (
            f"Structural coherence {coherence:.4f} < 0.65 "
            f"({coherent}/{total_checked} hierarchy relationships preserved). "
            f"The alignment must preserve parent-child relationships between ontologies."
        )
