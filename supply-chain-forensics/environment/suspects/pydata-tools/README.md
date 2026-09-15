# pydata-tools

Lightweight data manipulation and transformation utilities for Python.

## Installation

```bash
pip install pydata-tools
```

## Usage

```python
from pydata_tools import DataFrame, transform

df = DataFrame.from_csv('data.csv')
result = transform.normalize(df, columns=['price', 'quantity'])
```

## Features

- Fast CSV/JSON/Parquet reading
- Column transformations
- Data normalization
- Statistical aggregations
- Memory-efficient chunked processing
