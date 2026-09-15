"""Data transformation utilities"""


def normalize(df, columns=None):
    """Min-max normalize specified columns."""
    data = df.to_dict()
    cols = columns or df.columns

    for col in cols:
        values = [float(row.get(col, 0)) for row in data]
        min_val = min(values)
        max_val = max(values)
        range_val = max_val - min_val if max_val != min_val else 1

        for row in data:
            if col in row:
                row[col] = (float(row[col]) - min_val) / range_val

    from .core import DataFrame
    return DataFrame(data, df.columns)


def scale(df, columns=None, factor=1.0):
    """Scale specified columns by a factor."""
    data = df.to_dict()
    cols = columns or df.columns

    for col in cols:
        for row in data:
            if col in row:
                row[col] = float(row[col]) * factor

    from .core import DataFrame
    return DataFrame(data, df.columns)


def encode_categorical(df, column):
    """One-hot encode a categorical column."""
    data = df.to_dict()
    categories = list(set(row.get(column, '') for row in data))
    categories.sort()

    new_columns = df.columns + [f"{column}_{cat}" for cat in categories]

    for row in data:
        val = row.get(column, '')
        for cat in categories:
            row[f"{column}_{cat}"] = 1 if val == cat else 0

    from .core import DataFrame
    return DataFrame(data, new_columns)
