A ROS2 Jazzy workspace at `/app/ros2_ws/` contains a sensor data processing pipeline designed around four nodes:

1. **sensor_publisher** — lifecycle-managed node that generates synthetic sensor readings on `/sensor/raw`
2. **data_processor** — lifecycle-managed node that applies calibration parameters to raw data and publishes on `/sensor/processed`
3. **anomaly_filter** — lifecycle-managed node that performs statistical outlier detection on processed data and publishes clean readings on `/sensor/filtered`
4. **result_writer** — standard node that collects 10 filtered readings and writes them to `/app/output/results.csv`

The pipeline is non-functional. The workspace has multiple issues that prevent it from building and producing correct output. In addition, the `anomaly_filter` node exists only as an empty stub — you must design and implement it as a fully functional lifecycle-managed node that integrates correctly with the rest of the pipeline's communication and lifecycle patterns.

When complete, `ros2 launch data_pipeline pipeline_launch.py` should run the full 4-node pipeline and produce `/app/output/results.csv` containing 10 correctly calibrated sensor readings with proper CSV formatting.

## Output Schema

The output file `/app/output/results.csv` must be a standard CSV with a header row followed by exactly 10 data rows. The schema is:

| Column        | Type    | Description                                                                 |
|---------------|---------|-----------------------------------------------------------------------------|
| `sensor_id`   | integer | The sensor identifier (uint32 from the source message)                      |
| `temperature` | float   | Calibrated temperature value: `raw_temperature * scale + offset`            |
| `humidity`    | float   | Calibrated humidity value: `raw_humidity * scale + offset`                  |
| `pressure`    | float   | Calibrated pressure value: `raw_pressure * scale + offset`                  |
| `is_valid`    | boolean | Python boolean string (`True` or `False`). True when calibrated values fall within valid sensor ranges: temperature in [-40, 85], humidity in [0, 100], pressure in [300, 1100] |

Column order must be exactly: `sensor_id,temperature,humidity,pressure,is_valid`. Calibration parameters (`calibration_offset` and `calibration_scale`) are loaded from the workspace's parameter configuration file by the `data_processor` node.

ROS2 Jazzy is installed at `/opt/ros/jazzy/`. The workspace uses `colcon` for building.