CREATE TABLE capsules (
    capsule_id TEXT PRIMARY KEY,
    field TEXT NOT NULL,
    language TEXT NOT NULL,
    num_runs INTEGER NOT NULL
);

CREATE TABLE run_metrics (
    capsule_id TEXT NOT NULL,
    run_index INTEGER NOT NULL,
    metric_name TEXT NOT NULL,
    metric_type TEXT NOT NULL CHECK(metric_type IN ('numeric', 'string', 'list')),
    numeric_value REAL,
    text_value TEXT,
    PRIMARY KEY (capsule_id, run_index, metric_name),
    FOREIGN KEY (capsule_id) REFERENCES capsules(capsule_id)
);

-- capsule-6038: Computer Science, Python, 3 runs
INSERT INTO capsules VALUES ('capsule-6038', 'Computer Science', 'Python', 3);
INSERT INTO run_metrics VALUES ('capsule-6038', 0, 'accuracy', 'numeric', 0.85, NULL);
INSERT INTO run_metrics VALUES ('capsule-6038', 0, 'loss', 'numeric', 0.342, NULL);
INSERT INTO run_metrics VALUES ('capsule-6038', 0, 'best_model', 'string', NULL, 'RandomForest');
INSERT INTO run_metrics VALUES ('capsule-6038', 1, 'accuracy', 'numeric', 0.87, NULL);
INSERT INTO run_metrics VALUES ('capsule-6038', 1, 'loss', 'numeric', 0.338, NULL);
INSERT INTO run_metrics VALUES ('capsule-6038', 1, 'best_model', 'string', NULL, 'RandomForest');
INSERT INTO run_metrics VALUES ('capsule-6038', 2, 'accuracy', 'numeric', 0.86, NULL);
INSERT INTO run_metrics VALUES ('capsule-6038', 2, 'loss', 'numeric', 0.340, NULL);
INSERT INTO run_metrics VALUES ('capsule-6038', 2, 'best_model', 'string', NULL, 'RandomForest');

-- capsule-7291: Medical Sciences, R, 5 runs
INSERT INTO capsules VALUES ('capsule-7291', 'Medical Sciences', 'R', 5);
INSERT INTO run_metrics VALUES ('capsule-7291', 0, 'rmse', 'numeric', 2.34, NULL);
INSERT INTO run_metrics VALUES ('capsule-7291', 0, 'mae', 'numeric', 1.82, NULL);
INSERT INTO run_metrics VALUES ('capsule-7291', 0, 'fig_correlation_plot', 'numeric', 0.78, NULL);
INSERT INTO run_metrics VALUES ('capsule-7291', 1, 'rmse', 'numeric', 2.56, NULL);
INSERT INTO run_metrics VALUES ('capsule-7291', 1, 'mae', 'numeric', 1.95, NULL);
INSERT INTO run_metrics VALUES ('capsule-7291', 1, 'fig_correlation_plot', 'numeric', 0.78, NULL);
INSERT INTO run_metrics VALUES ('capsule-7291', 2, 'rmse', 'numeric', 2.41, NULL);
INSERT INTO run_metrics VALUES ('capsule-7291', 2, 'mae', 'numeric', 1.87, NULL);
INSERT INTO run_metrics VALUES ('capsule-7291', 2, 'fig_correlation_plot', 'numeric', 0.78, NULL);
INSERT INTO run_metrics VALUES ('capsule-7291', 3, 'rmse', 'numeric', 2.38, NULL);
INSERT INTO run_metrics VALUES ('capsule-7291', 3, 'mae', 'numeric', 1.84, NULL);
INSERT INTO run_metrics VALUES ('capsule-7291', 3, 'fig_correlation_plot', 'numeric', 0.78, NULL);
INSERT INTO run_metrics VALUES ('capsule-7291', 4, 'rmse', 'numeric', 2.51, NULL);
INSERT INTO run_metrics VALUES ('capsule-7291', 4, 'mae', 'numeric', 1.90, NULL);
INSERT INTO run_metrics VALUES ('capsule-7291', 4, 'fig_correlation_plot', 'numeric', 0.78, NULL);

-- capsule-4157: Social Sciences, Python, 3 runs
INSERT INTO capsules VALUES ('capsule-4157', 'Social Sciences', 'Python', 3);
INSERT INTO run_metrics VALUES ('capsule-4157', 0, 'precision', 'numeric', 72.5, NULL);
INSERT INTO run_metrics VALUES ('capsule-4157', 0, 'method_name', 'string', NULL, 'SVM');
INSERT INTO run_metrics VALUES ('capsule-4157', 0, 'selected_features', 'list', NULL, '[1, 3, 5, 7]');
INSERT INTO run_metrics VALUES ('capsule-4157', 1, 'precision', 'numeric', 73.1, NULL);
INSERT INTO run_metrics VALUES ('capsule-4157', 1, 'method_name', 'string', NULL, 'SVM');
INSERT INTO run_metrics VALUES ('capsule-4157', 1, 'selected_features', 'list', NULL, '[1, 3, 5, 7]');
INSERT INTO run_metrics VALUES ('capsule-4157', 2, 'precision', 'numeric', 71.8, NULL);
INSERT INTO run_metrics VALUES ('capsule-4157', 2, 'method_name', 'string', NULL, 'SVM');
INSERT INTO run_metrics VALUES ('capsule-4157', 2, 'selected_features', 'list', NULL, '[1, 3, 5, 7]');

-- capsule-8523: Computer Science, Python, 4 runs
INSERT INTO capsules VALUES ('capsule-8523', 'Computer Science', 'Python', 4);
INSERT INTO run_metrics VALUES ('capsule-8523', 0, 'f1_score', 'numeric', 0.891, NULL);
INSERT INTO run_metrics VALUES ('capsule-8523', 0, 'fig_roc_auc', 'numeric', 0.95, NULL);
INSERT INTO run_metrics VALUES ('capsule-8523', 1, 'f1_score', 'numeric', 0.903, NULL);
INSERT INTO run_metrics VALUES ('capsule-8523', 1, 'fig_roc_auc', 'numeric', 0.96, NULL);
INSERT INTO run_metrics VALUES ('capsule-8523', 2, 'f1_score', 'numeric', 0.897, NULL);
INSERT INTO run_metrics VALUES ('capsule-8523', 2, 'fig_roc_auc', 'numeric', 0.94, NULL);
INSERT INTO run_metrics VALUES ('capsule-8523', 3, 'f1_score', 'numeric', 0.885, NULL);
INSERT INTO run_metrics VALUES ('capsule-8523', 3, 'fig_roc_auc', 'numeric', 0.95, NULL);

-- capsule-3429: Medical Sciences, Python, 3 runs
INSERT INTO capsules VALUES ('capsule-3429', 'Medical Sciences', 'Python', 3);
INSERT INTO run_metrics VALUES ('capsule-3429', 0, 'convergence_rate', 'numeric', 45.2, NULL);
INSERT INTO run_metrics VALUES ('capsule-3429', 0, 'fig_loss_curve_endpoint', 'numeric', 0.0023, NULL);
INSERT INTO run_metrics VALUES ('capsule-3429', 1, 'convergence_rate', 'numeric', 45.2, NULL);
INSERT INTO run_metrics VALUES ('capsule-3429', 1, 'fig_loss_curve_endpoint', 'numeric', 0.0023, NULL);
INSERT INTO run_metrics VALUES ('capsule-3429', 2, 'convergence_rate', 'numeric', 45.2, NULL);
INSERT INTO run_metrics VALUES ('capsule-3429', 2, 'fig_loss_curve_endpoint', 'numeric', 0.0023, NULL);

-- capsule-1984: Social Sciences, R, 3 runs
INSERT INTO capsules VALUES ('capsule-1984', 'Social Sciences', 'R', 3);
INSERT INTO run_metrics VALUES ('capsule-1984', 0, 'coefficient_a', 'numeric', -0.0342, NULL);
INSERT INTO run_metrics VALUES ('capsule-1984', 0, 'coefficient_b', 'numeric', 1.2567, NULL);
INSERT INTO run_metrics VALUES ('capsule-1984', 0, 'model_type', 'string', NULL, 'OLS');
INSERT INTO run_metrics VALUES ('capsule-1984', 1, 'coefficient_a', 'numeric', -0.0342, NULL);
INSERT INTO run_metrics VALUES ('capsule-1984', 1, 'coefficient_b', 'numeric', 1.2567, NULL);
INSERT INTO run_metrics VALUES ('capsule-1984', 1, 'model_type', 'string', NULL, 'OLS');
INSERT INTO run_metrics VALUES ('capsule-1984', 2, 'coefficient_a', 'numeric', -0.0342, NULL);
INSERT INTO run_metrics VALUES ('capsule-1984', 2, 'coefficient_b', 'numeric', 1.2567, NULL);
INSERT INTO run_metrics VALUES ('capsule-1984', 2, 'model_type', 'string', NULL, 'OLS');

-- capsule-5610: Computer Science, Python, 3 runs
INSERT INTO capsules VALUES ('capsule-5610', 'Computer Science', 'Python', 3);
INSERT INTO run_metrics VALUES ('capsule-5610', 0, 'train_loss', 'numeric', 0.0460, NULL);
INSERT INTO run_metrics VALUES ('capsule-5610', 0, 'val_auc', 'numeric', 0.9376, NULL);
INSERT INTO run_metrics VALUES ('capsule-5610', 1, 'train_loss', 'numeric', 0.0538, NULL);
INSERT INTO run_metrics VALUES ('capsule-5610', 1, 'val_auc', 'numeric', 0.9372, NULL);
INSERT INTO run_metrics VALUES ('capsule-5610', 2, 'train_loss', 'numeric', 0.0503, NULL);
INSERT INTO run_metrics VALUES ('capsule-5610', 2, 'val_auc', 'numeric', 0.9320, NULL);

-- capsule-2847: Medical Sciences, R, 3 runs
INSERT INTO capsules VALUES ('capsule-2847', 'Medical Sciences', 'R', 3);
INSERT INTO run_metrics VALUES ('capsule-2847', 0, 'sensitivity', 'numeric', 0.966, NULL);
INSERT INTO run_metrics VALUES ('capsule-2847', 0, 'specificity', 'numeric', 0.994, NULL);
INSERT INTO run_metrics VALUES ('capsule-2847', 0, 'confusion_matrix_fig', 'numeric', 145.0, NULL);
INSERT INTO run_metrics VALUES ('capsule-2847', 1, 'sensitivity', 'numeric', 0.966, NULL);
INSERT INTO run_metrics VALUES ('capsule-2847', 1, 'specificity', 'numeric', 0.994, NULL);
INSERT INTO run_metrics VALUES ('capsule-2847', 1, 'confusion_matrix_fig', 'numeric', 145.0, NULL);
INSERT INTO run_metrics VALUES ('capsule-2847', 2, 'sensitivity', 'numeric', 0.966, NULL);
INSERT INTO run_metrics VALUES ('capsule-2847', 2, 'specificity', 'numeric', 0.994, NULL);
INSERT INTO run_metrics VALUES ('capsule-2847', 2, 'confusion_matrix_fig', 'numeric', 145.0, NULL);
