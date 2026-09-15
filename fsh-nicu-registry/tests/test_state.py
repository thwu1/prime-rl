
import json
import os
import pytest

GENERATED_DIR = "/app/fsh-generated/resources"


def read_json(filename):
    filepath = os.path.join(GENERATED_DIR, filename)
    with open(filepath) as f:
        return json.load(f)


class TestSUSHICompilation:
    def test_sushi_exit_code(self):
        with open("/app/sushi_exit_code.txt") as f:
            exit_code = int(f.read().strip())
        assert exit_code == 0, "SUSHI compilation failed with non-zero exit code"

    def test_sushi_zero_errors(self):
        with open("/app/sushi_output.txt") as f:
            output = f.read()
        assert "0 Errors" in output or "0 Error(s)" in output, "SUSHI reported errors"


class TestNICUPatientProfile:
    def test_exists_and_type(self):
        sd = read_json("StructureDefinition-nicu-patient.json")
        assert sd["resourceType"] == "StructureDefinition"
        assert sd["type"] == "Patient"

    def test_has_birth_weight_extension(self):
        sd = read_json("StructureDefinition-nicu-patient.json")
        elements_json = json.dumps(sd["differential"]["element"])
        assert "birth-weight" in elements_json

    def test_has_gestational_age_extension(self):
        sd = read_json("StructureDefinition-nicu-patient.json")
        elements_json = json.dumps(sd["differential"]["element"])
        assert "gestational-age" in elements_json

    def test_identifier_slicing_exists(self):
        sd = read_json("StructureDefinition-nicu-patient.json")
        identifier_elements = [
            e for e in sd["differential"]["element"]
            if e["id"].startswith("Patient.identifier")
        ]
        has_slicing = any("slicing" in e for e in identifier_elements)
        assert has_slicing, "NICUPatient missing identifier slicing"

    def test_identifier_slicing_uses_pattern_discriminator(self):
        sd = read_json("StructureDefinition-nicu-patient.json")
        identifier_el = [
            e for e in sd["differential"]["element"]
            if e["id"] == "Patient.identifier" and "slicing" in e
        ]
        assert len(identifier_el) > 0, "Missing identifier element with slicing"
        discriminators = identifier_el[0]["slicing"].get("discriminator", [])
        assert any(
            d.get("type") == "pattern" for d in discriminators
        ), "Identifier slicing discriminator must be of type 'pattern'"

    def test_has_mrn_slice(self):
        sd = read_json("StructureDefinition-nicu-patient.json")
        identifier_elements = [
            e for e in sd["differential"]["element"]
            if e["id"].startswith("Patient.identifier")
        ]
        has_mrn = any("MRN" in e["id"] for e in identifier_elements)
        assert has_mrn, "NICUPatient missing MRN identifier slice"

    def test_has_invariant(self):
        sd = read_json("StructureDefinition-nicu-patient.json")
        has_constraint = any(
            "constraint" in e for e in sd["differential"]["element"]
        )
        assert has_constraint, "NICUPatient missing invariant constraint"

    def test_birthdate_required(self):
        sd = read_json("StructureDefinition-nicu-patient.json")
        bd_elements = [
            e for e in sd["differential"]["element"]
            if e["id"] == "Patient.birthDate"
        ]
        assert len(bd_elements) > 0, "NICUPatient missing birthDate constraint"
        assert bd_elements[0].get("min", 0) >= 1, "birthDate must be required (min >= 1)"

    def test_gender_required(self):
        sd = read_json("StructureDefinition-nicu-patient.json")
        gender_elements = [
            e for e in sd["differential"]["element"]
            if e["id"] == "Patient.gender"
        ]
        assert len(gender_elements) > 0, "NICUPatient missing gender constraint"
        assert gender_elements[0].get("min", 0) >= 1, "gender must be required (min >= 1)"


class TestNICUAdmissionProfile:
    def test_exists_and_type(self):
        sd = read_json("StructureDefinition-nicu-admission.json")
        assert sd["resourceType"] == "StructureDefinition"
        assert sd["type"] == "Encounter"

    def test_subject_constrained_to_nicu_patient(self):
        sd = read_json("StructureDefinition-nicu-admission.json")
        subject_elements = [
            e for e in sd["differential"]["element"]
            if e["id"] == "Encounter.subject"
        ]
        assert len(subject_elements) > 0, "NICUAdmission missing subject element"
        subject_json = json.dumps(subject_elements[0])
        assert "nicu-patient" in subject_json

    def test_has_admission_reason_extension(self):
        sd = read_json("StructureDefinition-nicu-admission.json")
        elements_json = json.dumps(sd["differential"]["element"])
        assert "admission-reason" in elements_json

    def test_has_apgar_scores_extension(self):
        sd = read_json("StructureDefinition-nicu-admission.json")
        elements_json = json.dumps(sd["differential"]["element"])
        assert "apgar-scores" in elements_json

    def test_class_binding_required_strength(self):
        sd = read_json("StructureDefinition-nicu-admission.json")
        class_elements = [
            e for e in sd["differential"]["element"]
            if e["id"] == "Encounter.class"
        ]
        assert len(class_elements) > 0, "NICUAdmission missing class element"
        binding = class_elements[0].get("binding", {})
        assert binding.get("strength") == "required", \
            "Encounter class binding must be required strength"


class TestNeonatalVitalSignsProfile:
    def test_exists_and_type(self):
        sd = read_json("StructureDefinition-neonatal-vital-signs.json")
        assert sd["resourceType"] == "StructureDefinition"
        assert sd["type"] == "Observation"

    def test_fixed_loinc_code(self):
        sd = read_json("StructureDefinition-neonatal-vital-signs.json")
        code_elements = [
            e for e in sd["differential"]["element"]
            if e["id"] == "Observation.code"
        ]
        assert len(code_elements) > 0
        code_json = json.dumps(code_elements[0])
        assert "85353-1" in code_json, \
            "NeonatalVitalSigns must have fixed LOINC code 85353-1"

    def test_component_slicing(self):
        sd = read_json("StructureDefinition-neonatal-vital-signs.json")
        component_elements = [
            e for e in sd["differential"]["element"]
            if e["id"].startswith("Observation.component")
        ]
        has_slicing = any("slicing" in e for e in component_elements)
        assert has_slicing, "NeonatalVitalSigns missing component slicing"

    def test_four_component_slices(self):
        sd = read_json("StructureDefinition-neonatal-vital-signs.json")
        component_elements = [
            e for e in sd["differential"]["element"]
            if e["id"].startswith("Observation.component") and ":" in e["id"]
        ]
        slice_names = set()
        for e in component_elements:
            after_colon = e["id"].split(":")[1]
            slice_name = after_colon.split(".")[0]
            slice_names.add(slice_name)
        assert len(slice_names) >= 4, \
            f"Expected 4+ component slices, got {len(slice_names)}: {slice_names}"

    def test_effective_only_datetime(self):
        sd = read_json("StructureDefinition-neonatal-vital-signs.json")
        effective_elements = [
            e for e in sd["differential"]["element"]
            if "effective" in e["id"].lower() and "type" in e
        ]
        assert len(effective_elements) > 0, "Missing effective[x] type constraint"
        types = effective_elements[0].get("type", [])
        type_codes = [t["code"] for t in types]
        assert "dateTime" in type_codes, "effective[x] must allow dateTime"
        assert len(type_codes) == 1, \
            "effective[x] must be constrained to only dateTime"


class TestExtensions:
    def test_birth_weight_exists(self):
        sd = read_json("StructureDefinition-birth-weight.json")
        assert sd["type"] == "Extension"

    def test_birth_weight_quantity_value(self):
        sd = read_json("StructureDefinition-birth-weight.json")
        value_elements = [
            e for e in sd["differential"]["element"]
            if "value" in e["id"].lower() and "type" in e
        ]
        has_quantity = any(
            any(t.get("code") == "Quantity" for t in e.get("type", []))
            for e in value_elements
        )
        assert has_quantity, "BirthWeight value must be Quantity"

    def test_birth_weight_ucum(self):
        sd = read_json("StructureDefinition-birth-weight.json")
        elements_json = json.dumps(sd["differential"]["element"])
        assert "unitsofmeasure" in elements_json, \
            "BirthWeight must reference UCUM system"

    def test_birth_weight_context_patient(self):
        sd = read_json("StructureDefinition-birth-weight.json")
        contexts = sd.get("context", [])
        assert len(contexts) > 0, "BirthWeight missing extension context"
        assert any(c.get("expression") == "Patient" for c in contexts)

    def test_gestational_age_exists(self):
        sd = read_json("StructureDefinition-gestational-age.json")
        assert sd["type"] == "Extension"

    def test_gestational_age_context_patient(self):
        sd = read_json("StructureDefinition-gestational-age.json")
        contexts = sd.get("context", [])
        assert len(contexts) > 0, "GestationalAge missing extension context"
        assert any(c.get("expression") == "Patient" for c in contexts)

    def test_admission_reason_exists(self):
        sd = read_json("StructureDefinition-admission-reason.json")
        assert sd["type"] == "Extension"

    def test_admission_reason_codeable_concept(self):
        sd = read_json("StructureDefinition-admission-reason.json")
        value_elements = [
            e for e in sd["differential"]["element"]
            if "value" in e["id"].lower() and "type" in e
        ]
        has_cc = any(
            any(t.get("code") == "CodeableConcept" for t in e.get("type", []))
            for e in value_elements
        )
        assert has_cc, "AdmissionReason value must be CodeableConcept"

    def test_apgar_scores_exists(self):
        sd = read_json("StructureDefinition-apgar-scores.json")
        assert sd["type"] == "Extension"

    def test_apgar_scores_is_complex(self):
        sd = read_json("StructureDefinition-apgar-scores.json")
        elements = sd["differential"]["element"]
        has_sub_extensions = any(
            "extension" in e["id"].lower() and ":" in e["id"] for e in elements
        )
        assert has_sub_extensions, \
            "APGARScores must be complex with named sub-extensions"

    def test_apgar_scores_has_invariant(self):
        sd = read_json("StructureDefinition-apgar-scores.json")
        has_constraint = any(
            "constraint" in e for e in sd["differential"]["element"]
        )
        assert has_constraint, "APGARScores missing invariant"


class TestTerminology:
    def test_codesystem_exists(self):
        cs = read_json("CodeSystem-nicu-admission-reason-cs.json")
        assert cs["resourceType"] == "CodeSystem"

    def test_codesystem_case_sensitive(self):
        cs = read_json("CodeSystem-nicu-admission-reason-cs.json")
        assert cs.get("caseSensitive") is True, \
            "CodeSystem must be caseSensitive"

    def test_codesystem_complete_content(self):
        cs = read_json("CodeSystem-nicu-admission-reason-cs.json")
        assert cs.get("content") == "complete", \
            "CodeSystem content must be 'complete'"

    def test_codesystem_minimum_codes(self):
        cs = read_json("CodeSystem-nicu-admission-reason-cs.json")
        concepts = cs.get("concept", [])
        assert len(concepts) >= 6, \
            f"Expected 6+ concepts, got {len(concepts)}"

    def test_codesystem_required_codes(self):
        cs = read_json("CodeSystem-nicu-admission-reason-cs.json")
        codes = {c["code"] for c in cs.get("concept", [])}
        required = {
            "prematurity", "low-birth-weight", "respiratory-distress",
            "neonatal-jaundice", "birth-asphyxia", "congenital-anomaly",
        }
        missing = required - codes
        assert not missing, f"CodeSystem missing required codes: {missing}"

    def test_admission_reason_valueset(self):
        vs = read_json("ValueSet-nicu-admission-reason-vs.json")
        assert vs["resourceType"] == "ValueSet"

    def test_encounter_class_valueset(self):
        vs = read_json("ValueSet-nicu-encounter-class-vs.json")
        assert vs["resourceType"] == "ValueSet"

    def test_encounter_class_valueset_codes(self):
        vs = read_json("ValueSet-nicu-encounter-class-vs.json")
        compose = vs.get("compose", {})
        includes = compose.get("include", [])
        all_concepts = []
        for inc in includes:
            all_concepts.extend(inc.get("concept", []))
        codes = {c["code"] for c in all_concepts}
        expected = {"IMP", "ACUTE", "EMER"}
        assert expected.issubset(codes), \
            f"NICUEncounterClassVS missing codes: {expected - codes}"


class TestInstances:
    def test_patient_exists(self):
        patient = read_json("Patient-BabySmithPatient.json")
        assert patient["resourceType"] == "Patient"

    def test_patient_demographics(self):
        patient = read_json("Patient-BabySmithPatient.json")
        assert patient.get("gender") == "female"
        assert patient.get("birthDate") == "2024-01-15"

    def test_patient_has_mrn(self):
        patient = read_json("Patient-BabySmithPatient.json")
        identifiers = patient.get("identifier", [])
        mrn_ids = [i for i in identifiers if i.get("value") == "MRN-12345"]
        assert len(mrn_ids) > 0, "Patient missing MRN identifier"

    def test_patient_birth_weight_extension(self):
        patient = read_json("Patient-BabySmithPatient.json")
        extensions = patient.get("extension", [])
        has_bw = any("birth-weight" in e.get("url", "") for e in extensions)
        assert has_bw, "Patient missing birth weight extension"

    def test_patient_birth_weight_value(self):
        patient = read_json("Patient-BabySmithPatient.json")
        extensions = patient.get("extension", [])
        bw_ext = [e for e in extensions if "birth-weight" in e.get("url", "")]
        assert len(bw_ext) > 0
        vq = bw_ext[0].get("valueQuantity", {})
        assert vq.get("value") == 1250, "Birth weight should be 1250"
        assert vq.get("code") == "g", "Birth weight unit code should be g"

    def test_patient_gestational_age_extension(self):
        patient = read_json("Patient-BabySmithPatient.json")
        extensions = patient.get("extension", [])
        has_ga = any("gestational-age" in e.get("url", "") for e in extensions)
        assert has_ga, "Patient missing gestational age extension"

    def test_patient_gestational_age_value(self):
        patient = read_json("Patient-BabySmithPatient.json")
        extensions = patient.get("extension", [])
        ga_ext = [e for e in extensions if "gestational-age" in e.get("url", "")]
        assert len(ga_ext) > 0
        vq = ga_ext[0].get("valueQuantity", {})
        assert vq.get("value") == 30, "Gestational age should be 30"
        assert vq.get("code") == "wk", "Gestational age unit code should be wk"

    def test_encounter_exists(self):
        encounter = read_json("Encounter-BabySmithAdmission.json")
        assert encounter["resourceType"] == "Encounter"
        assert encounter.get("status") == "in-progress"

    def test_encounter_references_patient(self):
        encounter = read_json("Encounter-BabySmithAdmission.json")
        subject = encounter.get("subject", {})
        ref = subject.get("reference", "")
        assert "BabySmithPatient" in ref, \
            "Encounter must reference BabySmithPatient"

    def test_encounter_has_extensions(self):
        encounter = read_json("Encounter-BabySmithAdmission.json")
        extensions = encounter.get("extension", [])
        has_reason = any(
            "admission-reason" in e.get("url", "") for e in extensions
        )
        has_apgar = any(
            "apgar-scores" in e.get("url", "") for e in extensions
        )
        assert has_reason, "Encounter missing admission reason extension"
        assert has_apgar, "Encounter missing APGAR scores extension"

    def test_encounter_apgar_values(self):
        encounter = read_json("Encounter-BabySmithAdmission.json")
        extensions = encounter.get("extension", [])
        apgar_ext = [
            e for e in extensions if "apgar-scores" in e.get("url", "")
        ]
        assert len(apgar_ext) > 0
        sub_exts = apgar_ext[0].get("extension", [])
        one_min = [s for s in sub_exts if s.get("url") == "oneMinute"]
        five_min = [s for s in sub_exts if s.get("url") == "fiveMinute"]
        assert len(one_min) > 0, "Missing oneMinute sub-extension"
        assert len(five_min) > 0, "Missing fiveMinute sub-extension"
        assert one_min[0].get("valueUnsignedInt") == 7
        assert five_min[0].get("valueUnsignedInt") == 9

    def test_observation_exists(self):
        obs = read_json("Observation-BabySmithVitals.json")
        assert obs["resourceType"] == "Observation"
        assert obs.get("status") == "final"

    def test_observation_references_patient(self):
        obs = read_json("Observation-BabySmithVitals.json")
        subject = obs.get("subject", {})
        ref = subject.get("reference", "")
        assert "BabySmithPatient" in ref, \
            "Observation must reference BabySmithPatient"

    def test_observation_has_components(self):
        obs = read_json("Observation-BabySmithVitals.json")
        components = obs.get("component", [])
        assert len(components) >= 4, \
            f"Expected 4+ components, got {len(components)}"

    def test_observation_component_values(self):
        obs = read_json("Observation-BabySmithVitals.json")
        components = obs.get("component", [])
        codes_to_values = {}
        for comp in components:
            codings = comp.get("code", {}).get("coding", [{}])
            code = codings[0].get("code", "") if codings else ""
            vq = comp.get("valueQuantity", {})
            codes_to_values[code] = vq.get("value")
        assert codes_to_values.get("8867-4") == 145, "Heart rate should be 145"
        assert codes_to_values.get("9279-1") == 52, "Respiratory rate should be 52"
        assert codes_to_values.get("2708-6") == 95, "SpO2 should be 95"
        temp = codes_to_values.get("8310-5")
        assert temp is not None, "Temperature component missing"
        assert abs(temp - 36.8) < 0.1, f"Temperature should be ~36.8, got {temp}"
