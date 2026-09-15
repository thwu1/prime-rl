A geometric evaluation pipeline at `/app/cad_eval.py` compares pairs of CadQuery-generated 3D models. It reads pair definitions from `/app/manifest.json`, executes CadQuery scripts to produce STL meshes, and computes similarity metrics between each pair.

The pipeline executes without errors but produces incorrect metric values. Identify and fix all issues so that:

```
python3 /app/cad_eval.py /app/manifest.json /app/results.json
```

generates accurate geometric evaluation output.

CadQuery and its dependencies are pre-installed. Model scripts are at `/app/scripts/`.