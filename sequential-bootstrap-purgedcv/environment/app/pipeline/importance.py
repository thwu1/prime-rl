"""Feature importance computation using Mean Decrease Impurity."""

import pandas as pd


def compute_mdi_importance(clf, feature_names):
    """Compute MDI feature importance from a trained ensemble classifier.

    Returns a Series of feature importances indexed by feature name.
    """
    return pd.Series(clf.feature_importances_, index=feature_names)
