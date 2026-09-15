#!/usr/bin/env python3
"""
Fleet safety forensics: parse ArduPilot DataFlash binary logs,
compute safety scores, reconstruct causal fault chains,
evaluate failsafe response timeliness, determine airworthiness,
and generate fleet-level operational recommendations.
"""

import json
import os

from pymavlink import mavutil

# Known causal pathways in ArduPilot's sensor fusion architecture.
# Each tuple (cause, effect) means the cause anomaly can physically
# produce the effect anomaly through the described mechanism.
CAUSAL_PATHS = {
    ("mechanical_vibration", "ekf_divergence"),  # IMU saturation -> EKF prediction corruption
    ("gps_glitch", "ekf_divergence"),            # position observation loss -> EKF drift
}


def parse_flight(filepath):
    """Parse a DataFlash binary log using pymavlink."""
    mlog = mavutil.mavlink_connection(filepath)

    data = {
        'GPS': [], 'EKF4': [], 'VIBE': [], 'BARO': [],
        'MODE': [], 'PARM': [],
    }
    total_non_fmt = 0

    while True:
        msg = mlog.recv_match()
        if msg is None:
            break
        msg_type = msg.get_type()
        if msg_type == 'FMT':
            continue
        total_non_fmt += 1

        if msg_type == 'GPS':
            data['GPS'].append({
                'TimeUS': msg.TimeUS, 'Status': msg.Status, 'Alt': msg.Alt,
            })
        elif msg_type == 'EKF4':
            data['EKF4'].append({
                'TimeUS': msg.TimeUS, 'Variance': msg.Variance,
            })
        elif msg_type == 'VIBE':
            data['VIBE'].append({
                'TimeUS': msg.TimeUS, 'VibeZ': msg.VibeZ,
            })
        elif msg_type == 'BARO':
            data['BARO'].append({
                'TimeUS': msg.TimeUS, 'Alt': msg.Alt,
            })
        elif msg_type == 'MODE':
            data['MODE'].append({
                'TimeUS': msg.TimeUS, 'Mode': msg.Mode, 'Reason': msg.Reason,
            })
        elif msg_type == 'PARM':
            data['PARM'].append({
                'TimeUS': msg.TimeUS, 'Name': msg.Name, 'Value': msg.Value,
            })

    return data, total_non_fmt


def detect_anomalies(data):
    """Detect all anomaly events with timestamps, ordered chronologically."""
    # Get FS_EKF_THRESH using last-write-wins
    fs_thresh = 0.8
    for m in data['PARM']:
        if m['Name'] == 'FS_EKF_THRESH':
            fs_thresh = m['Value']

    anomalies = []

    # GPS glitch: first GPS where Status < 2
    for m in sorted(data['GPS'], key=lambda x: x['TimeUS']):
        if m['Status'] < 2:
            anomalies.append({
                'event': 'gps_glitch',
                'time_us': m['TimeUS'],
                'time_sec': int(m['TimeUS'] // 1_000_000),
            })
            break

    # EKF divergence: first EKF4 where Variance > FS_EKF_THRESH
    for m in sorted(data['EKF4'], key=lambda x: x['TimeUS']):
        if m['Variance'] > fs_thresh:
            anomalies.append({
                'event': 'ekf_divergence',
                'time_us': m['TimeUS'],
                'time_sec': int(m['TimeUS'] // 1_000_000),
            })
            break

    # Mechanical vibration: first VIBE where VibeZ > 30.0
    for m in sorted(data['VIBE'], key=lambda x: x['TimeUS']):
        if m['VibeZ'] > 30.0:
            anomalies.append({
                'event': 'mechanical_vibration',
                'time_us': m['TimeUS'],
                'time_sec': int(m['TimeUS'] // 1_000_000),
            })
            break

    anomalies.sort(key=lambda a: a['time_us'])
    return anomalies


def classify_fault_chain(anomalies):
    """Classify each anomaly as primary, secondary, or independent
    based on known causal pathways in ArduPilot's sensor fusion architecture."""
    if not anomalies:
        return []

    chain = []
    for i, anomaly in enumerate(anomalies):
        if i == 0:
            category = 'primary'
        else:
            # Check if any prior anomaly has a known causal path to this one
            has_cause = any(
                (prior['event'], anomaly['event']) in CAUSAL_PATHS
                for prior in anomalies[:i]
            )
            category = 'secondary' if has_cause else 'independent'

        chain.append({
            'event': anomaly['event'],
            'time_sec': anomaly['time_sec'],
            'category': category,
        })

    return chain


def analyze_flight(data, total_non_fmt, param_ranges):
    """Compute safety metrics and forensic analysis for a single flight."""
    result = {}
    result['total_messages'] = total_non_fmt

    # Max barometric altitude
    baro_alts = [m['Alt'] for m in data['BARO']]
    result['max_altitude_m'] = round(max(baro_alts), 1) if baro_alts else 0.0

    # GPS quality score
    gps_msgs = data['GPS']
    if gps_msgs:
        good_gps = sum(1 for m in gps_msgs if m['Status'] >= 3)
        gps_score = good_gps / len(gps_msgs) * 100
    else:
        gps_score = 0.0
    result['gps_score'] = round(gps_score, 2)

    # EKF health score
    ekf_msgs = sorted(data['EKF4'], key=lambda m: m['TimeUS'])
    peak_variance = max((m['Variance'] for m in ekf_msgs), default=0.0)
    ekf_score = max(0.0, 100.0 - peak_variance * 80.0)
    result['ekf_score'] = round(ekf_score, 2)

    # Vibration score
    vibe_msgs = sorted(data['VIBE'], key=lambda m: m['TimeUS'])
    peak_vibe_z = max((m['VibeZ'] for m in vibe_msgs), default=0.0)
    vibe_score = max(0.0, 100.0 - max(0.0, peak_vibe_z - 10.0) * 2.0)
    result['vibe_score'] = round(vibe_score, 2)

    # Parameter compliance (last-write-wins)
    parm_msgs = data['PARM']
    final_params = {}
    for m in parm_msgs:
        final_params[m['Name']] = m['Value']

    misconfigured = []
    checked = 0
    compliant = 0
    for pname, pval in final_params.items():
        if pname in param_ranges:
            checked += 1
            r = param_ranges[pname]
            if pval < r['min'] or pval > r['max']:
                misconfigured.append(pname)
            else:
                compliant += 1

    param_score = (compliant / checked * 100) if checked > 0 else 100.0
    result['param_score'] = round(param_score, 2)
    result['misconfigured_params'] = sorted(misconfigured)

    # Mode stability
    mode_msgs = sorted(data['MODE'], key=lambda m: m['TimeUS'])
    unplanned = sum(1 for m in mode_msgs if m['Reason'] >= 2)
    mode_score = max(0.0, 100.0 - unplanned * 25.0)
    result['mode_score'] = round(mode_score, 2)

    # Composite score (from unrounded sub-scores)
    composite = (gps_score * 0.30 + ekf_score * 0.25 + vibe_score * 0.20 +
                 param_score * 0.15 + mode_score * 0.10)
    result['composite_score'] = round(composite, 2)

    # Risk level
    if composite >= 80:
        result['risk_level'] = 'low'
    elif composite >= 60:
        result['risk_level'] = 'moderate'
    elif composite >= 40:
        result['risk_level'] = 'high'
    else:
        result['risk_level'] = 'critical'

    # Detect anomalies and build causal fault chain
    anomalies = detect_anomalies(data)
    fault_chain = classify_fault_chain(anomalies)
    result['root_cause'] = anomalies[0]['event'] if anomalies else 'none'
    result['fault_chain'] = fault_chain

    # Failsafe response assessment
    failsafe_modes = [m for m in mode_msgs if m['Reason'] >= 2]
    if anomalies and failsafe_modes:
        first_anomaly_sec = anomalies[0]['time_sec']
        first_failsafe_sec = int(failsafe_modes[0]['TimeUS'] // 1_000_000)
        delay = first_failsafe_sec - first_anomaly_sec
        result['failsafe_response_sec'] = delay
        result['failsafe_assessment'] = 'timely' if delay <= 10 else 'delayed'
    else:
        result['failsafe_response_sec'] = None
        result['failsafe_assessment'] = 'not_applicable'

    # Airworthiness classification
    if not fault_chain and not misconfigured:
        result['airworthiness'] = 'airworthy'
    elif not fault_chain:
        result['airworthiness'] = 'conditional'
    else:
        result['airworthiness'] = 'grounded'

    # Required maintenance actions
    actions = set()
    for entry in fault_chain:
        if entry['event'] == 'mechanical_vibration' and entry['category'] in ('primary', 'independent'):
            actions.add('mechanical_inspection')
        if entry['event'] == 'gps_glitch' and entry['category'] in ('primary', 'independent'):
            actions.add('gps_inspection')
        if entry['event'] == 'ekf_divergence' and entry['category'] == 'primary':
            actions.add('ekf_calibration')
    if misconfigured:
        actions.add('parameter_update')
    result['required_actions'] = sorted(actions)

    return result


def main():
    with open('/app/param_ranges.json', 'r') as f:
        param_ranges = json.load(f)

    flight_names = ['alpha', 'bravo', 'charlie']
    per_flight = {}

    for name in flight_names:
        filepath = os.path.join('/app/flights', f'flight_{name}.bin')
        data, total_non_fmt = parse_flight(filepath)
        per_flight[name] = analyze_flight(data, total_non_fmt, param_ranges)

    # Risk ranking: most dangerous (lowest composite) first
    ranking = sorted(flight_names, key=lambda n: per_flight[n]['composite_score'])

    # Systemic issues: parameters misconfigured across ALL flights
    all_misconfig = [set(per_flight[n]['misconfigured_params']) for n in flight_names]
    systemic = sorted(set.intersection(*all_misconfig)) if all_misconfig else []

    # Corrective actions: map misconfigured params to their defaults
    corrective = {}
    for name in flight_names:
        actions = {}
        for param in per_flight[name]['misconfigured_params']:
            if param in param_ranges:
                actions[param] = param_ranges[param]['default']
        corrective[name] = dict(sorted(actions.items()))

    # Fleet-level airworthiness counts
    airworthy_count = sum(1 for n in flight_names if per_flight[n]['airworthiness'] == 'airworthy')
    conditional_count = sum(1 for n in flight_names if per_flight[n]['airworthiness'] == 'conditional')
    grounded_count = sum(1 for n in flight_names if per_flight[n]['airworthiness'] == 'grounded')

    # Fleet operational recommendation
    if grounded_count == len(flight_names):
        fleet_action = 'full_ground'
    elif grounded_count > 0 and systemic:
        fleet_action = 'fleet_review'
    elif grounded_count > 0:
        fleet_action = 'partial_ground'
    else:
        fleet_action = 'continue_operations'

    output = {
        'per_flight': per_flight,
        'risk_ranking': ranking,
        'systemic_issues': systemic,
        'corrective_actions': corrective,
        'fleet_airworthy_count': airworthy_count,
        'fleet_conditional_count': conditional_count,
        'fleet_grounded_count': grounded_count,
        'recommended_fleet_action': fleet_action,
    }

    with open('/app/fleet_assessment.json', 'w') as f:
        json.dump(output, f, indent=2)

    print("Fleet assessment complete.")


if __name__ == '__main__':
    main()
