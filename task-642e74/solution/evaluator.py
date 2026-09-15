#!/usr/bin/env python3

"""CMS165 Controlling High Blood Pressure - eCQM Population Evaluator (Solution).

This evaluator implements the CMS165 measure logic as specified in the CQL definition,
evaluating FHIR R4 patient bundles against the measure's population criteria:
- Initial Population: age 18-85, essential hypertension in first 6 months, qualifying encounter
- Denominator: equals Initial Population
- Denominator Exclusions: hospice, pregnancy, renal disease, palliative care
- Numerator: systolic < 140 AND diastolic < 90 on most recent qualifying BP day

Data sources:
- Terminology: SQLite database at /app/terminology.db
- Configuration: FHIR Parameters XML at /app/measure-parameters.xml
- Patients: FHIR R4 Bundle JSON files in /app/patients/
"""

import json
import sqlite3
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path


# ---------------------------------------------------------------------------
# Data Loading — SQLite and XML
# ---------------------------------------------------------------------------

def load_valuesets_from_db(db_path):
    """Query the terminology SQLite database and return value sets.

    Discovers the schema, joins value_sets with vs_expansion and coding_systems,
    and returns a dict: {title: [{system, code, display}, ...]}.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT vs.title, cs.uri, e.code, e.display
        FROM vs_expansion e
        JOIN value_sets vs ON e.vs_id = vs.vs_id
        JOIN coding_systems cs ON e.system_id = cs.system_id
        ORDER BY vs.title, cs.uri, e.code
    """)

    valuesets = {}
    for title, system_uri, code, display in cursor.fetchall():
        if title not in valuesets:
            valuesets[title] = []
        valuesets[title].append({
            "system": system_uri,
            "code": code,
            "display": display or ""
        })

    conn.close()
    return valuesets


def load_measurement_period_from_xml(xml_path):
    """Parse FHIR Parameters XML to extract measurement period dates."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    ns = {'fhir': 'http://hl7.org/fhir'}

    for param in root.findall('fhir:parameter', ns):
        name_elem = param.find('fhir:name', ns)
        if name_elem is not None and name_elem.get('value') == 'measurementPeriod':
            period = param.find('fhir:valuePeriod', ns)
            if period is not None:
                start = period.find('fhir:start', ns).get('value')
                end = period.find('fhir:end', ns).get('value')
                return start, end

    raise ValueError("measurementPeriod parameter not found in XML")


def map_db_titles_to_evaluator_names(db_valuesets):
    """Map database value set titles to the internal names used by the evaluator.

    Database titles come from VSAC and may differ from the short names used
    in CQL valueset declarations. This mapping resolves those differences.
    """
    title_to_name = {
        "Essential Hypertension": "Essential Hypertension",
        "Adult Outpatient Qualifying Encounters": "Qualifying Encounters",
        "Encounter Inpatient": "Encounter Inpatient",
        "Emergency Department Evaluation and Management Visit": "Emergency Department Visit",
        "Pregnancy Dx": "Pregnancy",
        "End Stage Renal Disease": "End Stage Renal Disease",
        "Chronic Kidney Disease, Stage 5": "Chronic Kidney Disease, Stage 5",
        "Kidney Transplant Recipient": "Kidney Transplant Recipient",
        "Kidney Transplant": "Kidney Transplant",
        "Dialysis Services": "Dialysis Services",
        "ESRD Monthly Outpatient Services": "ESRD Monthly Outpatient Services",
        "Hospice Encounter": "Hospice",
        "Palliative Care Intervention": "Palliative Care",
    }

    mapped = {}
    for db_title, eval_name in title_to_name.items():
        if db_title in db_valuesets:
            mapped[eval_name] = db_valuesets[db_title]
    return mapped


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def parse_date(s):
    """Parse a FHIR date or dateTime string to a Python date object."""
    if not s:
        return None
    s = str(s)
    if 'T' in s:
        s = s.replace('Z', '+00:00')
        return datetime.fromisoformat(s).date()
    return date.fromisoformat(s)


def code_matches(codeable_concept, valueset_entries):
    """Check if a FHIR CodeableConcept matches any code in a value set definition."""
    if not codeable_concept or not valueset_entries:
        return False
    for coding in codeable_concept.get('coding', []):
        sys = coding.get('system', '')
        code = coding.get('code', '')
        for entry in valueset_entries:
            if entry['system'] == sys and entry['code'] == code:
                return True
    return False


def is_verified(condition):
    """Implement CQL .verified() filter for Conditions."""
    vs = condition.get('verificationStatus')
    if vs is None:
        return True
    for coding in vs.get('coding', []):
        if coding.get('code') in ('refuted', 'entered-in-error'):
            return False
    return True


def prevalence_interval(condition):
    """Compute CQL prevalenceInterval() for a Condition."""
    onset = parse_date(condition.get('onsetDateTime'))
    if not onset:
        onset_period = condition.get('onsetPeriod')
        if onset_period:
            onset = parse_date(onset_period.get('start'))

    abatement = parse_date(condition.get('abatementDateTime'))

    clinical_status = None
    cs = condition.get('clinicalStatus', {})
    for coding in cs.get('coding', []):
        clinical_status = coding.get('code')

    if clinical_status in ('active', 'recurrence', 'relapse'):
        return (onset, None)
    elif abatement:
        return (onset, abatement)
    else:
        return (onset, None)


def intervals_overlap(a_start, a_end, b_start, b_end, b_end_exclusive=False):
    """Check if interval A overlaps interval B."""
    if a_start is None:
        return False

    if b_end is not None:
        if b_end_exclusive:
            if a_start >= b_end:
                return False
        else:
            if a_start > b_end:
                return False

    if a_end is not None and b_start is not None:
        if b_start > a_end:
            return False

    return True


def age_in_years_at(birth_date, reference_date):
    """Calculate age in complete years at a given reference date."""
    age = reference_date.year - birth_date.year
    if (reference_date.month, reference_date.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


def date_range(start, end):
    """Generate all dates from start to end, inclusive."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


# ---------------------------------------------------------------------------
# Measure Evaluator
# ---------------------------------------------------------------------------

class CMS165Evaluator:
    """Evaluates CMS165 (Controlling High Blood Pressure) measure logic."""

    def __init__(self, valuesets, mp_start_str, mp_end_str):
        self.vs = valuesets
        self.mp_start = parse_date(mp_start_str)
        self.mp_end = parse_date(mp_end_str)
        self.mp_6m = date(
            self.mp_start.year + (self.mp_start.month + 6 - 1) // 12,
            (self.mp_start.month + 6 - 1) % 12 + 1,
            self.mp_start.day
        )

    def evaluate_patient(self, bundle):
        """Evaluate a single patient bundle against CMS165."""
        res = self._parse_bundle(bundle)

        ip = self._initial_population(res)
        denom = ip
        denex = self._denominator_exclusions(res) if denom else False
        numer = self._numerator(res) if (denom and not denex) else False

        return {
            "initial_population": ip,
            "denominator": denom,
            "denominator_exclusion": denex,
            "numerator": numer
        }

    def _parse_bundle(self, bundle):
        """Extract FHIR resources by type from a Bundle."""
        resources = {
            "Patient": [], "Condition": [], "Encounter": [],
            "Observation": [], "Procedure": [], "ServiceRequest": []
        }
        for entry in bundle.get("entry", []):
            r = entry.get("resource", {})
            rt = r.get("resourceType", "")
            if rt in resources:
                resources[rt].append(r)
        return resources

    # -------------------------------------------------------------------
    # Initial Population
    # -------------------------------------------------------------------

    def _initial_population(self, res):
        """CMS165 Initial Population:
        - AgeInYearsAt(date from end of MP) in [18, 85]
        - Has Essential Hypertension Diagnosis (verified, prevalence overlaps first 6 months)
        - Has qualifying outpatient encounter during MP
        """
        if not res["Patient"]:
            return False
        patient = res["Patient"][0]

        bd = parse_date(patient.get("birthDate"))
        if not bd:
            return False
        age = age_in_years_at(bd, self.mp_end)
        if not (18 <= age <= 85):
            return False

        htn_vs = self.vs.get("Essential Hypertension", [])
        has_htn = False
        for cond in res["Condition"]:
            if code_matches(cond.get("code"), htn_vs) and is_verified(cond):
                pi = prevalence_interval(cond)
                if intervals_overlap(pi[0], pi[1], self.mp_start, self.mp_6m,
                                     b_end_exclusive=True):
                    has_htn = True
                    break
        if not has_htn:
            return False

        enc_vs = self.vs.get("Qualifying Encounters", [])
        has_enc = False
        for enc in res["Encounter"]:
            if enc.get("status") != "finished":
                continue
            enc_types = enc.get("type", [])
            if any(code_matches(t, enc_vs) for t in enc_types):
                period = enc.get("period", {})
                start_d = parse_date(period.get("start"))
                if start_d and self.mp_start <= start_d <= self.mp_end:
                    has_enc = True
                    break
        if not has_enc:
            return False

        return True

    # -------------------------------------------------------------------
    # Denominator Exclusions
    # -------------------------------------------------------------------

    def _denominator_exclusions(self, res):
        """CMS165 Denominator Exclusions:
        - Hospice services
        - Pregnancy or renal diagnosis overlapping MP
        - ESRD procedures ending on or before end of MP
        - ESRD encounters starting on or before end of MP
        - Palliative care in MP
        """
        hospice_vs = self.vs.get("Hospice", [])
        for sr in res["ServiceRequest"]:
            if code_matches(sr.get("code"), hospice_vs):
                status = sr.get("status", "")
                if status in ("active", "completed", "on-hold"):
                    authored = parse_date(sr.get("authoredOn"))
                    if authored and self.mp_start <= authored <= self.mp_end:
                        return True
        for proc in res["Procedure"]:
            if code_matches(proc.get("code"), hospice_vs):
                if proc.get("status") == "completed":
                    perf = self._procedure_end(proc)
                    if perf and perf <= self.mp_end:
                        return True

        excl_vs_names = [
            "Pregnancy", "End Stage Renal Disease",
            "Chronic Kidney Disease, Stage 5", "Kidney Transplant Recipient"
        ]
        for vs_name in excl_vs_names:
            vs = self.vs.get(vs_name, [])
            for cond in res["Condition"]:
                if code_matches(cond.get("code"), vs) and is_verified(cond):
                    pi = prevalence_interval(cond)
                    if intervals_overlap(pi[0], pi[1], self.mp_start, self.mp_end):
                        return True

        proc_vs_names = ["Kidney Transplant", "Dialysis Services"]
        for vs_name in proc_vs_names:
            vs = self.vs.get(vs_name, [])
            for proc in res["Procedure"]:
                if proc.get("status") == "completed" and code_matches(proc.get("code"), vs):
                    perf_end = self._procedure_end(proc)
                    if perf_end and perf_end <= self.mp_end:
                        return True

        esrd_enc_vs = self.vs.get("ESRD Monthly Outpatient Services", [])
        for enc in res["Encounter"]:
            if enc.get("status") == "finished":
                if any(code_matches(t, esrd_enc_vs) for t in enc.get("type", [])):
                    period = enc.get("period", {})
                    start_d = parse_date(period.get("start"))
                    if start_d and start_d <= self.mp_end:
                        return True

        palliative_vs = self.vs.get("Palliative Care", [])
        for cond in res["Condition"]:
            if code_matches(cond.get("code"), palliative_vs) and is_verified(cond):
                pi = prevalence_interval(cond)
                if intervals_overlap(pi[0], pi[1], self.mp_start, self.mp_end):
                    return True
        for proc in res["Procedure"]:
            if code_matches(proc.get("code"), palliative_vs):
                if proc.get("status") == "completed":
                    perf_start = self._procedure_start(proc)
                    if perf_start and self.mp_start <= perf_start <= self.mp_end:
                        return True

        return False

    def _procedure_end(self, proc):
        """Get the end date of a procedure's performed period."""
        if 'performedPeriod' in proc:
            return parse_date(proc['performedPeriod'].get('end'))
        return parse_date(proc.get('performedDateTime'))

    def _procedure_start(self, proc):
        """Get the start date of a procedure's performed period."""
        if 'performedPeriod' in proc:
            return parse_date(proc['performedPeriod'].get('start'))
        return parse_date(proc.get('performedDateTime'))

    # -------------------------------------------------------------------
    # Numerator
    # -------------------------------------------------------------------

    def _numerator(self, res):
        """CMS165 Numerator:
        - Has Systolic Blood Pressure Less Than 140
        - AND Has Diastolic Blood Pressure Less Than 90
        Based on lowest reading on most recent qualifying blood pressure day.
        """
        qualifying = self._qualifying_bp_readings(res)
        if not qualifying:
            return False

        systolic_dates = set()
        diastolic_dates = set()
        for bp in qualifying:
            eff = parse_date(bp.get("effectiveDateTime"))
            if not eff:
                continue
            for comp in bp.get("component", []):
                comp_code = self._component_loinc(comp)
                if comp_code == "8480-6":
                    systolic_dates.add(eff)
                elif comp_code == "8462-4":
                    diastolic_dates.add(eff)

        bp_days = systolic_dates & diastolic_dates
        if not bp_days:
            return False

        most_recent_day = max(bp_days)

        systolics = []
        diastolics = []
        for bp in qualifying:
            eff = parse_date(bp.get("effectiveDateTime"))
            if eff != most_recent_day:
                continue
            for comp in bp.get("component", []):
                comp_code = self._component_loinc(comp)
                val = comp.get("valueQuantity", {}).get("value")
                if val is not None:
                    if comp_code == "8480-6":
                        systolics.append(val)
                    elif comp_code == "8462-4":
                        diastolics.append(val)

        if not systolics or not diastolics:
            return False

        return min(systolics) < 140 and min(diastolics) < 90

    def _qualifying_bp_readings(self, res):
        """Get qualifying blood pressure readings per CMS165 CQL logic.

        Path 1 (without clause): BP readings NOT on same day as any
            inpatient or ED encounter.
        Path 2 (encounter class filter): BP readings whose encounter
            reference does NOT have a disqualifying class code, during MP.
        """
        BP_PANEL_CODE = "85354-9"

        all_bps = [
            obs for obs in res["Observation"]
            if obs.get("status") in ("final", "amended", "corrected")
            and any(
                c.get("code") == BP_PANEL_CODE
                for c in obs.get("code", {}).get("coding", [])
            )
        ]

        if not all_bps:
            return []

        enc_map = {}
        for enc in res["Encounter"]:
            eid = enc.get("id", "")
            if eid:
                enc_map[eid] = enc

        DISQ_CLASSES = {"EMER", "IMP", "ACUTE", "NONAC", "PRENC", "SS"}
        inpatient_vs = self.vs.get("Encounter Inpatient", [])
        ed_vs = self.vs.get("Emergency Department Visit", [])

        disqualifying_day_set = set()
        for enc in res["Encounter"]:
            if enc.get("status") != "finished":
                continue
            enc_class_code = enc.get("class", {}).get("code", "")
            is_disq = enc_class_code in ("IMP", "ACUTE", "NONAC", "EMER")
            if not is_disq:
                for t in enc.get("type", []):
                    if code_matches(t, inpatient_vs) or code_matches(t, ed_vs):
                        is_disq = True
                        break
            if is_disq:
                period = enc.get("period", {})
                ps = parse_date(period.get("start"))
                pe = parse_date(period.get("end"))
                if ps and pe:
                    for d in date_range(ps, pe):
                        disqualifying_day_set.add(d)

        path1_ids = set()
        for bp in all_bps:
            eff = parse_date(bp.get("effectiveDateTime"))
            if eff and eff not in disqualifying_day_set:
                path1_ids.add(bp.get("id"))

        path2_ids = set()
        for bp in all_bps:
            eff = parse_date(bp.get("effectiveDateTime"))
            if not eff or not (self.mp_start <= eff <= self.mp_end):
                continue
            enc_ref = bp.get("encounter", {}).get("reference", "")
            if not enc_ref:
                continue
            enc_id = enc_ref.split("/")[-1]
            enc = enc_map.get(enc_id)
            if enc:
                enc_class_code = enc.get("class", {}).get("code", "")
                if enc_class_code in DISQ_CLASSES:
                    continue
            path2_ids.add(bp.get("id"))

        qualifying_ids = path1_ids | path2_ids
        return [bp for bp in all_bps if bp.get("id") in qualifying_ids]

    def _component_loinc(self, component):
        """Get the LOINC code from a BP observation component."""
        for coding in component.get("code", {}).get("coding", []):
            if coding.get("system") == "http://loinc.org":
                return coding.get("code", "")
        return ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    patients_dir = Path("/app/patients")

    # Load terminology from SQLite database
    db_valuesets = load_valuesets_from_db("/app/terminology.db")
    valuesets = map_db_titles_to_evaluator_names(db_valuesets)

    # Load measurement period from FHIR Parameters XML
    mp_start_str, mp_end_str = load_measurement_period_from_xml(
        "/app/measure-parameters.xml"
    )

    evaluator = CMS165Evaluator(valuesets, mp_start_str, mp_end_str)

    results = {}
    for pf in sorted(patients_dir.glob("*.json")):
        patient_id = pf.stem
        with open(pf) as f:
            bundle = json.load(f)
        results[patient_id] = evaluator.evaluate_patient(bundle)

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"Evaluated {len(results)} patients. Results written to /app/results.json")


if __name__ == "__main__":
    main()
