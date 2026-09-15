#!/bin/bash

# Deploy the Section 121 calculator implementation
cp /solution/section121_impl.py /app/section121.py

# Verify the implementation loads and passes a basic sanity check
python3 -c "
import sys
sys.path.insert(0, '/app')
from section121 import compute_exclusion

result = compute_exclusion({
    'date_of_sale': '2024-06-15',
    'gain': 200000,
    'return_type': 'single',
    'person': {
        'ownership_periods': [{'begin': '2018-01-01', 'end': '2024-06-15'}],
        'usage_periods': [{'begin': '2018-01-01', 'end': '2024-06-15'}],
        'prior_sale_date': None
    }
})
assert result['excluded_amount'] == 200000, f'Sanity check failed: excluded={result[\"excluded_amount\"]}'
assert result['gain_cap'] == 250000, f'Sanity check failed: cap={result[\"gain_cap\"]}'
print('Section 121 calculator deployed and verified.')
"
