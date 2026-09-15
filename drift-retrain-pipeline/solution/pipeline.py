#!/usr/bin/env python3
"""
MLOps Drift-Triggered Retraining Pipeline

Detects data drift, retrains with hyperparameter sweep, evaluates with
fairness constraints, and produces a progressive rollout deployment plan.
"""

import json
import os
import yaml
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde, ks_2samp
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split, cross_val_score, ParameterGrid
from sklearn.metrics import f1_score, precision_score, recall_score, accuracy_score
import mlflow
import mlflow.sklearn


def load_config():
    with open('/app/config.yaml', 'r') as f:
        return yaml.safe_load(f)


def load_data():
    ref = pd.read_csv('/app/data/reference.csv')
    prod = pd.read_csv('/app/data/production.csv')
    return ref, prod


# ═══════════════════ DRIFT DETECTION ═══════════════════


def compute_psi(reference, production, n_bins=10):
    """Population Stability Index with quantile-based binning."""
    breakpoints = np.percentile(reference, np.linspace(0, 100, n_bins + 1))
    breakpoints[0] = -np.inf
    breakpoints[-1] = np.inf

    ref_counts = np.histogram(reference, bins=breakpoints)[0].astype(float)
    prod_counts = np.histogram(production, bins=breakpoints)[0].astype(float)

    ref_pct = ref_counts / len(reference)
    prod_pct = prod_counts / len(production)

    # Epsilon smoothing for zero-count bins
    eps = 1e-4
    ref_pct = np.where(ref_pct == 0, eps, ref_pct)
    prod_pct = np.where(prod_pct == 0, eps, prod_pct)

    psi = float(np.sum((prod_pct - ref_pct) * np.log(prod_pct / ref_pct)))
    return psi


def compute_kde_overlap(reference, production):
    """KDE intersection overlap area via numerical integration."""
    kde_ref = gaussian_kde(reference, bw_method='silverman')
    kde_prod = gaussian_kde(production, bw_method='silverman')

    combined = np.concatenate([reference, production])
    margin = 3 * np.std(combined)
    x_min = combined.min() - margin
    x_max = combined.max() + margin
    x = np.linspace(x_min, x_max, 2000)

    overlap = float(np.trapz(np.minimum(kde_ref(x), kde_prod(x)), x))
    return min(overlap, 1.0)


def detect_drift(ref_data, prod_data, config):
    """Run drift detection on all configured features."""
    features = config['drift_detection']['features']
    thresholds = config['drift_detection']['thresholds']
    n_bins = config['drift_detection']['psi_bins']

    drift_results = {}
    drifted_features = []

    for feature in features:
        ref_vals = ref_data[feature].values.astype(float)
        prod_vals = prod_data[feature].values.astype(float)

        ks_stat, ks_pvalue = ks_2samp(ref_vals, prod_vals)
        psi = compute_psi(ref_vals, prod_vals, n_bins)
        kde_overlap = compute_kde_overlap(ref_vals, prod_vals)

        is_drifted = bool(
            ks_pvalue < thresholds['ks_pvalue'] and
            psi > thresholds['psi'] and
            kde_overlap < thresholds['kde_overlap']
        )

        drift_results[feature] = {
            'ks_statistic': float(ks_stat),
            'ks_pvalue': float(ks_pvalue),
            'psi': float(psi),
            'kde_overlap': float(kde_overlap),
            'is_drifted': is_drifted
        }

        if is_drifted:
            drifted_features.append(feature)

    return {
        'features': drift_results,
        'drifted_features': drifted_features,
        'n_drifted': len(drifted_features)
    }


# ═══════════════════ MODEL RETRAINING ═══════════════════


def run_sweep(X_train, y_train, X_test, y_test, config):
    """Grid sweep over hyperparameters, logging every trial to MLflow."""
    sweep_params = config['retraining']['sweep']
    random_state = config['retraining']['random_state']
    cv_folds = config['retraining']['cv_folds']

    param_grid = list(ParameterGrid(sweep_params))
    best_f1 = -1.0
    best_run_id = None
    best_params = None

    for params in param_grid:
        with mlflow.start_run(run_name=f"sweep_{params}") as run:
            model = RandomForestClassifier(
                random_state=random_state,
                **params
            )

            cv_scores = cross_val_score(
                model, X_train, y_train,
                cv=cv_folds,
                scoring=config['retraining']['scoring']
            )

            model.fit(X_train, y_train)

            for k, v in params.items():
                mlflow.log_param(k, v)
            mlflow.log_metric('cv_f1_mean', float(np.mean(cv_scores)))
            mlflow.log_metric('cv_f1_std', float(np.std(cv_scores)))

            y_pred = model.predict(X_test)
            test_f1 = float(f1_score(y_test, y_pred))
            mlflow.log_metric('test_f1', test_f1)
            mlflow.log_metric('test_precision', float(precision_score(y_test, y_pred)))
            mlflow.log_metric('test_recall', float(recall_score(y_test, y_pred)))
            mlflow.log_metric('test_accuracy', float(accuracy_score(y_test, y_pred)))

            mlflow.sklearn.log_model(model, 'model')

            if test_f1 > best_f1:
                best_f1 = test_f1
                best_run_id = run.info.run_id
                best_params = dict(params)

    return best_run_id, best_f1, best_params


# ═══════════════════ MODEL EVALUATION ═══════════════════


def compute_classification_metrics(model, X, y):
    y_pred = model.predict(X)
    return {
        'f1_score': float(f1_score(y, y_pred)),
        'precision': float(precision_score(y, y_pred)),
        'recall': float(recall_score(y, y_pred)),
        'accuracy': float(accuracy_score(y, y_pred))
    }


def compute_equalized_odds_gap(model, X, y, groups):
    """Equalized odds gap = max(|TPR_A - TPR_B|, |FPR_A - FPR_B|)."""
    y_pred = model.predict(X)
    y = np.array(y)
    y_pred = np.array(y_pred)
    groups = np.array(groups)

    group_metrics = {}
    for gval in sorted(set(groups)):
        mask = groups == gval
        y_g = y[mask]
        yp_g = y_pred[mask]

        pos_mask = y_g == 1
        tpr = float((yp_g[pos_mask] == 1).sum() / pos_mask.sum()) if pos_mask.sum() > 0 else 0.0

        neg_mask = y_g == 0
        fpr = float((yp_g[neg_mask] == 1).sum() / neg_mask.sum()) if neg_mask.sum() > 0 else 0.0

        group_metrics[str(gval)] = {'tpr': tpr, 'fpr': fpr}

    group_keys = list(group_metrics.keys())
    tpr_gap = abs(group_metrics[group_keys[0]]['tpr'] - group_metrics[group_keys[1]]['tpr'])
    fpr_gap = abs(group_metrics[group_keys[0]]['fpr'] - group_metrics[group_keys[1]]['fpr'])

    return {
        'equalized_odds_gap': float(max(tpr_gap, fpr_gap)),
        'tpr_gap': float(tpr_gap),
        'fpr_gap': float(fpr_gap),
        'group_metrics': group_metrics
    }


def evaluate_models(baseline_model, candidate_model, X_test, y_test, groups_test):
    baseline_metrics = compute_classification_metrics(baseline_model, X_test, y_test)
    candidate_metrics = compute_classification_metrics(candidate_model, X_test, y_test)
    baseline_fairness = compute_equalized_odds_gap(baseline_model, X_test, y_test, groups_test)
    candidate_fairness = compute_equalized_odds_gap(candidate_model, X_test, y_test, groups_test)

    f1_imp_pct = (
        (candidate_metrics['f1_score'] - baseline_metrics['f1_score'])
        / baseline_metrics['f1_score']
    ) * 100 if baseline_metrics['f1_score'] > 0 else 0.0

    return baseline_metrics, candidate_metrics, baseline_fairness, candidate_fairness, f1_imp_pct


# ═══════════════════ DEPLOYMENT DECISION ═══════════════════


def make_deployment_decision(f1_imp_pct, candidate_fairness, baseline_fairness, config):
    rules = config['deployment']['rollout_rules']
    max_gap = config['evaluation']['fairness']['max_allowed_gap']

    candidate_gap = candidate_fairness['equalized_odds_gap']
    baseline_gap = baseline_fairness['equalized_odds_gap']

    fairness_degraded = candidate_gap > max_gap or candidate_gap > baseline_gap
    perf_regressed = f1_imp_pct < 0

    if rules['block_on_fairness_degradation'] and fairness_degraded:
        return 'blocked', 'fairness_degradation', None
    elif rules['block_on_performance_regression'] and perf_regressed:
        return 'blocked', 'performance_regression', None
    elif f1_imp_pct >= rules['immediate_threshold_pct']:
        schedule = [{'stage': 1, 'traffic_pct': 100, 'delay_hours': 0}]
        reason = (f"f1_improvement_{f1_imp_pct:.2f}pct_exceeds_"
                  f"{rules['immediate_threshold_pct']}pct")
        return 'immediate', reason, schedule
    elif f1_imp_pct >= rules['gradual_threshold_pct']:
        stages = rules['gradual_stages']
        interval = rules['gradual_interval_hours']
        schedule = [
            {'stage': i + 1, 'traffic_pct': pct, 'delay_hours': i * interval}
            for i, pct in enumerate(stages)
        ]
        reason = (f"f1_improvement_{f1_imp_pct:.2f}pct_between_"
                  f"{rules['gradual_threshold_pct']}_"
                  f"{rules['immediate_threshold_pct']}pct")
        return 'gradual', reason, schedule
    else:
        reason = (f"f1_improvement_{f1_imp_pct:.2f}pct_below_"
                  f"{rules['gradual_threshold_pct']}pct")
        return 'no_rollout', reason, None


# ═══════════════════ MAIN PIPELINE ═══════════════════


def main():
    config = load_config()
    ref_data, prod_data = load_data()
    os.makedirs('/app/output', exist_ok=True)

    # ── Stage 1: Drift Detection ──
    print("Stage 1: Drift Detection")
    drift_report = detect_drift(ref_data, prod_data, config)
    with open('/app/output/drift_report.json', 'w') as f:
        json.dump(drift_report, f, indent=2)
    print(f"  Drifted features: {drift_report['drifted_features']}")

    if drift_report['n_drifted'] == 0:
        print("No drift detected. Pipeline complete.")
        plan = {'decision': 'no_action', 'reason': 'no_drift_detected',
                'rollout_schedule': None}
        with open('/app/output/deployment_plan.json', 'w') as f:
            json.dump(plan, f, indent=2)
        return

    # ── Stage 2: Model Retraining ──
    print("Stage 2: Model Retraining")
    feature_cols = config['drift_detection']['features']
    combined = pd.concat([ref_data, prod_data], ignore_index=True)

    X = combined[feature_cols]
    y = combined['failure']
    groups = combined['group']

    X_train, X_test, y_train, y_test, groups_train, groups_test = train_test_split(
        X, y, groups,
        test_size=config['evaluation']['test_size'],
        random_state=config['retraining']['random_state'],
        stratify=y
    )

    mlflow.set_tracking_uri('file:///app/mlruns')
    mlflow.set_experiment(config['retraining']['experiment_name'])

    best_run_id, best_f1, best_params = run_sweep(
        X_train, y_train, X_test, y_test, config
    )
    print(f"  Best model: F1={best_f1:.4f}, params={best_params}")

    # ── Stage 3: Model Evaluation ──
    print("Stage 3: Model Evaluation")
    baseline_run_id = open('/app/baseline_run_id.txt').read().strip()
    baseline_model = mlflow.sklearn.load_model(f'runs:/{baseline_run_id}/model')
    candidate_model = mlflow.sklearn.load_model(f'runs:/{best_run_id}/model')

    (baseline_metrics, candidate_metrics,
     baseline_fairness, candidate_fairness, f1_imp_pct) = evaluate_models(
        baseline_model, candidate_model, X_test, y_test, groups_test
    )

    eval_report = {
        'baseline': {
            'run_id': baseline_run_id,
            'metrics': baseline_metrics,
            'fairness': baseline_fairness
        },
        'candidate': {
            'run_id': best_run_id,
            'params': best_params,
            'metrics': candidate_metrics,
            'fairness': candidate_fairness
        },
        'comparison': {
            'f1_improvement_pct': float(f1_imp_pct),
            'f1_improvement_abs': float(
                candidate_metrics['f1_score'] - baseline_metrics['f1_score']
            )
        }
    }
    with open('/app/output/evaluation_report.json', 'w') as f:
        json.dump(eval_report, f, indent=2)
    print(f"  F1 improvement: {f1_imp_pct:.2f}%")
    print(f"  Candidate fairness gap: {candidate_fairness['equalized_odds_gap']:.4f}")
    print(f"  Baseline fairness gap: {baseline_fairness['equalized_odds_gap']:.4f}")

    # ── Stage 4: Deployment Decision ──
    print("Stage 4: Deployment Decision")
    decision, reason, schedule = make_deployment_decision(
        f1_imp_pct, candidate_fairness, baseline_fairness, config
    )

    deployment_plan = {
        'decision': decision,
        'reason': reason,
        'candidate_run_id': best_run_id,
        'rollout_schedule': schedule,
        'f1_improvement_pct': float(f1_imp_pct),
        'fairness_gap': float(candidate_fairness['equalized_odds_gap']),
        'baseline_fairness_gap': float(baseline_fairness['equalized_odds_gap'])
    }

    if decision in ('immediate', 'gradual'):
        model_uri = f'runs:/{best_run_id}/model'
        mv = mlflow.register_model(model_uri, 'predictive_maintenance_model')
        deployment_plan['registered_model_version'] = mv.version

    with open('/app/output/deployment_plan.json', 'w') as f:
        json.dump(deployment_plan, f, indent=2)
    print(f"  Decision: {decision} ({reason})")


if __name__ == '__main__':
    main()
