#!/usr/bin/env python3
"""
CQL eCQM Population Evaluator for CMS165 - Controlling High Blood Pressure.
Uses SQLite for terminology lookups and jq-style FHIR bundle processing.
"""

import json
import sqlite3
import subprocess
from datetime import date, timedelta
from pathlib import Path


def load_measurement_period():
    with open('/app/measurement_period.json') as f:
        mp = json.load(f)
    return date.fromisoformat(mp['start']), date.fromisoformat(mp['end'])


MP_START, MP_END = load_measurement_period()
FIRST_6_MONTHS_END_EXCLUSIVE = date(MP_START.year, MP_START.month + 6, MP_START.day)
FIRST_6_MONTHS_END_INCLUSIVE = FIRST_6_MONTHS_END_EXCLUSIVE - timedelta(days=1)
FRAILTY_LOOKBACK_START = date(MP_START.year - 1, MP_START.month, MP_START.day)
MAX_DATE = date(9999, 12, 31)

# SQLite terminology connection
TERM_DB = sqlite3.connect('/app/terminology.db')
TERM_DB.row_factory = sqlite3.Row

# Cache value set code sets for performance
_VS_CACHE = {}


def get_valueset_codes(vs_name):
    """Query SQLite for all (system, code) pairs in a value set by title or URL."""
    if vs_name in _VS_CACHE:
        return _VS_CACHE[vs_name]
    rows = TERM_DB.execute('''
        SELECT c.system, c.code
        FROM codes c
        JOIN value_sets vs ON c.value_set_id = vs.id
        WHERE vs.title = ? OR vs.url = ?
    ''', (vs_name, vs_name)).fetchall()
    code_set = {(r['system'], r['code']) for r in rows}
    _VS_CACHE[vs_name] = code_set
    return code_set


def code_in_valueset(codings, vs_name):
    """Check if any coding matches a value set via SQLite lookup."""
    vs_codes = get_valueset_codes(vs_name)
    if not vs_codes:
        return False
    for coding in codings:
        if (coding.get('system'), coding.get('code')) in vs_codes:
            return True
    return False


def extract_resources_jq(bundle_path, resource_type):
    """Use jq to extract resources of a given type from a FHIR bundle."""
    jq_filter = f'.entry[].resource | select(.resourceType == "{resource_type}")'
    result = subprocess.run(
        ['jq', '-c', jq_filter, str(bundle_path)],
        capture_output=True, text=True
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    return [json.loads(line) for line in result.stdout.strip().split('\n') if line.strip()]


def get_code_codings(resource):
    code_obj = resource.get('code')
    if code_obj is None:
        return []
    return code_obj.get('coding', [])


def get_type_codings(resource):
    type_field = resource.get('type')
    if type_field is None:
        return []
    result = []
    if isinstance(type_field, list):
        for cc in type_field:
            result.extend(cc.get('coding', []))
    else:
        result.extend(type_field.get('coding', []))
    return result


def parse_date(s):
    if s is None:
        return None
    return date.fromisoformat(s[:10])


def age_at(birth_date_str, ref_date):
    bd = date.fromisoformat(birth_date_str)
    return ref_date.year - bd.year - ((ref_date.month, ref_date.day) < (bd.month, bd.day))


def condition_is_active(condition):
    cs = condition.get('clinicalStatus', {})
    for coding in cs.get('coding', []):
        if coding.get('code') in ('active', 'recurrence', 'relapse'):
            return True
    return False


def condition_is_confirmed_or_unspecified(condition):
    vs = condition.get('verificationStatus')
    if vs is None:
        return True
    for coding in vs.get('coding', []):
        if coding.get('code') in ('confirmed', 'provisional', 'differential'):
            return True
    return False


def prevalence_interval(condition):
    onset = parse_date(condition.get('onsetDateTime'))
    abatement = parse_date(condition.get('abatementDateTime'))
    if onset is None:
        return None, None
    if condition_is_active(condition):
        end = abatement if abatement is not None else MAX_DATE
        return onset, end
    else:
        return onset, abatement


def intervals_overlap(a_start, a_end, b_start, b_end):
    if a_start is None or b_start is None:
        return False
    a_end_eff = a_end if a_end is not None else a_start
    b_end_eff = b_end if b_end is not None else b_start
    return a_start <= b_end_eff and b_start <= a_end_eff


def encounter_during_period(encounter, period_start, period_end):
    enc_start = parse_date(encounter.get('period', {}).get('start'))
    enc_end = parse_date(encounter.get('period', {}).get('end'))
    if enc_start is None:
        return False
    if enc_end is None:
        enc_end = enc_start
    return period_start <= enc_start and enc_end <= period_end


def is_during_ed_or_inpatient(observation, all_encounters):
    obs_date = parse_date(observation.get('effectiveDateTime'))
    if obs_date is None:
        return False

    for enc in all_encounters:
        if enc.get('status') != 'finished':
            continue
        type_codings = get_type_codings(enc)
        if code_in_valueset(type_codings, 'Encounter Inpatient') or \
           code_in_valueset(type_codings, 'Emergency Department Visit'):
            enc_start = parse_date(enc.get('period', {}).get('start'))
            enc_end = parse_date(enc.get('period', {}).get('end'))
            if enc_start is None:
                continue
            if enc_end is None:
                enc_end = enc_start
            if enc_start <= obs_date <= enc_end:
                return True

    enc_ref = observation.get('encounter', {}).get('reference')
    if enc_ref:
        enc_id = enc_ref.split('/')[-1] if '/' in enc_ref else enc_ref
        for enc in all_encounters:
            if enc.get('id') == enc_id:
                enc_class = enc.get('class', {})
                class_code = enc_class.get('code', '')
                if class_code in ('EMER', 'IMP', 'ACUTE', 'NONAC', 'PRENC', 'SS'):
                    return True
                break

    return False


def evaluate_ipp(patient, conditions, encounters):
    patient_age = age_at(patient['birthDate'], MP_END)
    if patient_age < 18 or patient_age > 85:
        return False

    has_htn = False
    for cond in conditions:
        codings = get_code_codings(cond)
        if not code_in_valueset(codings, 'Essential Hypertension'):
            continue
        if not condition_is_active(cond):
            continue
        if not condition_is_confirmed_or_unspecified(cond):
            continue
        prev_start, prev_end = prevalence_interval(cond)
        if intervals_overlap(prev_start, prev_end, MP_START, FIRST_6_MONTHS_END_INCLUSIVE):
            has_htn = True
            break

    if not has_htn:
        return False

    qualifying_vs = [
        'Office Visit', 'Annual Wellness Visit',
        'Preventive Care Services Established Office Visit, 18 and Up',
        'Preventive Care Services Initial Office Visit, 18 and Up',
        'Home Healthcare Services', 'Outpatient Consultation', 'Telephone Visits',
    ]

    for enc in encounters:
        if enc.get('status') != 'finished':
            continue
        type_codings = get_type_codings(enc)
        for vs in qualifying_vs:
            if code_in_valueset(type_codings, vs):
                if encounter_during_period(enc, MP_START, MP_END):
                    return True

    return False


def evaluate_denex(patient, conditions, encounters, procedures):
    for enc in encounters:
        type_codings = get_type_codings(enc)
        if code_in_valueset(type_codings, 'Hospice Encounter'):
            enc_start = parse_date(enc.get('period', {}).get('start'))
            enc_end = parse_date(enc.get('period', {}).get('end'))
            if intervals_overlap(enc_start, enc_end, MP_START, MP_END):
                return True

    preg_renal_vs = [
        'Pregnancy', 'End Stage Renal Disease',
        'Kidney Transplant Recipient', 'Chronic Kidney Disease, Stage 5',
    ]
    for cond in conditions:
        codings = get_code_codings(cond)
        for vs in preg_renal_vs:
            if code_in_valueset(codings, vs):
                prev_start, prev_end = prevalence_interval(cond)
                if intervals_overlap(prev_start, prev_end, MP_START, MP_END):
                    return True

    esrd_proc_vs = ['Kidney Transplant', 'Dialysis Services']
    for proc in procedures:
        if proc.get('status') != 'completed':
            continue
        codings = get_code_codings(proc)
        for vs in esrd_proc_vs:
            if code_in_valueset(codings, vs):
                performed = proc.get('performedDateTime') or \
                    proc.get('performedPeriod', {}).get('end') or \
                    proc.get('performedPeriod', {}).get('start')
                proc_end_date = parse_date(performed)
                if proc_end_date is not None and proc_end_date <= MP_END:
                    return True

    for enc in encounters:
        if enc.get('status') != 'finished':
            continue
        type_codings = get_type_codings(enc)
        if code_in_valueset(type_codings, 'ESRD Monthly Outpatient Services'):
            enc_start = parse_date(enc.get('period', {}).get('start'))
            if enc_start is not None and enc_start <= MP_END:
                return True

    palliative_vs = ['Palliative Care Encounter', 'Palliative Care Intervention']
    for enc in encounters:
        type_codings = get_type_codings(enc)
        for vs in palliative_vs:
            if code_in_valueset(type_codings, vs):
                enc_start = parse_date(enc.get('period', {}).get('start'))
                enc_end = parse_date(enc.get('period', {}).get('end'))
                if intervals_overlap(enc_start, enc_end, MP_START, MP_END):
                    return True

    patient_age = age_at(patient['birthDate'], MP_END)
    if 66 <= patient_age <= 80:
        has_frailty = False
        has_adv_illness = False
        for cond in conditions:
            codings = get_code_codings(cond)
            if code_in_valueset(codings, 'Frailty Diagnosis'):
                prev_start, prev_end = prevalence_interval(cond)
                if intervals_overlap(prev_start, prev_end, FRAILTY_LOOKBACK_START, MP_END):
                    has_frailty = True
            if code_in_valueset(codings, 'Advanced Illness'):
                prev_start, prev_end = prevalence_interval(cond)
                if intervals_overlap(prev_start, prev_end, FRAILTY_LOOKBACK_START, MP_END):
                    has_adv_illness = True
        if has_frailty and has_adv_illness:
            return True

    if patient_age >= 81:
        for cond in conditions:
            codings = get_code_codings(cond)
            if code_in_valueset(codings, 'Frailty Diagnosis'):
                prev_start, prev_end = prevalence_interval(cond)
                if intervals_overlap(prev_start, prev_end, FRAILTY_LOOKBACK_START, MP_END):
                    return True

    return False


def evaluate_numerator(observations, encounters):
    qualifying_systolic_dates = []
    qualifying_diastolic_dates = []
    bp_observations = []

    for obs in observations:
        code_codings = get_code_codings(obs)
        is_bp = any(
            c.get('system') == 'http://loinc.org' and c.get('code') == '85354-9'
            for c in code_codings
        )
        if not is_bp:
            continue
        if obs.get('status') not in ('final', 'amended', 'corrected'):
            continue
        if is_during_ed_or_inpatient(obs, encounters):
            continue

        obs_date = parse_date(obs.get('effectiveDateTime'))
        if obs_date is None:
            continue
        if not (MP_START <= obs_date <= MP_END):
            continue

        bp_observations.append(obs)

        has_systolic = False
        has_diastolic = False
        for comp in obs.get('component', []):
            comp_codings = comp.get('code', {}).get('coding', [])
            comp_value = comp.get('valueQuantity', {}).get('value')
            if comp_value is None:
                continue
            if any(c.get('code') == '8480-6' for c in comp_codings):
                has_systolic = True
            if any(c.get('code') == '8462-4' for c in comp_codings):
                has_diastolic = True

        if has_systolic:
            qualifying_systolic_dates.append(obs_date)
        if has_diastolic:
            qualifying_diastolic_dates.append(obs_date)

    systolic_date_set = set(qualifying_systolic_dates)
    diastolic_date_set = set(qualifying_diastolic_dates)
    both_dates = sorted(systolic_date_set & diastolic_date_set)

    if not both_dates:
        return False

    most_recent_day = both_dates[-1]

    systolic_values = []
    diastolic_values = []

    for obs in bp_observations:
        obs_date = parse_date(obs.get('effectiveDateTime'))
        if obs_date != most_recent_day:
            continue
        for comp in obs.get('component', []):
            comp_codings = comp.get('code', {}).get('coding', [])
            comp_value = comp.get('valueQuantity', {}).get('value')
            if comp_value is None:
                continue
            if any(c.get('code') == '8480-6' for c in comp_codings):
                systolic_values.append(comp_value)
            if any(c.get('code') == '8462-4' for c in comp_codings):
                diastolic_values.append(comp_value)

    if not systolic_values or not diastolic_values:
        return False

    lowest_systolic = min(systolic_values)
    lowest_diastolic = min(diastolic_values)

    return lowest_systolic < 140 and lowest_diastolic < 90


def evaluate_patient(bundle_path):
    """Evaluate a patient bundle using jq for resource extraction and SQLite for terminology."""
    patient_list = extract_resources_jq(bundle_path, 'Patient')
    if not patient_list:
        return {'IPP': False, 'DENOM': False, 'DENEX': False, 'NUMER': False}
    patient = patient_list[0]

    conditions = extract_resources_jq(bundle_path, 'Condition')
    encounters = extract_resources_jq(bundle_path, 'Encounter')
    observations = extract_resources_jq(bundle_path, 'Observation')
    procedures = extract_resources_jq(bundle_path, 'Procedure')

    result = {'IPP': False, 'DENOM': False, 'DENEX': False, 'NUMER': False}

    if not evaluate_ipp(patient, conditions, encounters):
        return result
    result['IPP'] = True
    result['DENOM'] = True

    if evaluate_denex(patient, conditions, encounters, procedures):
        result['DENEX'] = True
        return result

    if evaluate_numerator(observations, encounters):
        result['NUMER'] = True

    return result


def main():
    # Use jq to list patient bundle files and extract metadata
    results = {}
    patients_dir = Path('/app/patients')

    for patient_file in sorted(patients_dir.glob('*.json')):
        patient_id = patient_file.stem
        results[patient_id] = evaluate_patient(patient_file)

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Evaluated {len(results)} patients")
    for pid, result in sorted(results.items()):
        flags = [k for k in ['IPP', 'DENOM', 'DENEX', 'NUMER'] if result[k]]
        print(f"  {pid}: {', '.join(flags) if flags else '(none)'}")


if __name__ == '__main__':
    main()
