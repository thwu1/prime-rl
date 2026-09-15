A partial implementation at `/app/evaluate_draft.py` computes surgical action triplet evaluation metrics for multi-label classification with bounding-box detection. It contains multiple bugs that cause its output to diverge from the reference library `ivtmetrics==0.1.5`. The bugs span different pipeline stages: component decomposition, recognition scoring, detection scoring, and association analysis.

Produce `/app/evaluate.py` that writes `/app/results.json` with all metrics matching `ivtmetrics==0.1.5` within 1e-6 tolerance. Your code must not import `ivtmetrics` at runtime. You may install it to study its API, source code, and numerical behavior.

Run `python3 /app/generate_data.py` to populate `/app/data/`.

**Inputs:**
- `/app/map_matrix.csv`: 100-row triplet-to-component mapping (columns: ivt,i,v,t,iv,it)
- `/app/data/recognition/video_{n}.npz`: NumPy archives with keys `targets` (F×100, int) and `predictions` (F×100, float)
- `/app/data/detection/video_{n}.json`: Per-frame lists with `gt` and `pred` entries as `[tripletID, toolID, confidence, x, y, w, h]`

**Required output** `/app/results.json`:
```json
{
  "recognition": {
    "video_ap": {
      "ivt": <float>, "ivt_per_class": [<100 values, null for NaN>],
      "i": <float>, "v": <float>, "t": <float>, "iv": <float>, "it": <float>
    },
    "global_ap": {"ivt": <float>}
  },
  "detection": {
    "video_ap": {
      "ivt": {"mAP": <float>, "mRec": <float>, "mPre": <float>},
      "i": {"mAP": <float>, "mRec": <float>, "mPre": <float>}
    },
    "association": {
      "lm": <float>, "plm": <float>, "ids": <float>,
      "idm": <float>, "mil": <float>, "fp": <float>, "fn": <float>
    }
  }
}
```

NaN values must be JSON `null`. Numeric tolerance: 1e-6.
