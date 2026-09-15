import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs_custom.msg import ProcessedData
import os
import csv


class ResultWriter(Node):
    def __init__(self):
        super().__init__('result_writer')
        self.declare_parameter('output_dir', '/app/output')
        self.declare_parameter('max_readings', 10)

        self._output_dir = self.get_parameter('output_dir').value
        self._max_readings = self.get_parameter('max_readings').value
        self._readings = []

        os.makedirs(self._output_dir, exist_ok=True)

        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )
        self._subscription = self.create_subscription(
            ProcessedData, '/sensor/filtered', self.write_callback, qos)
        self.get_logger().info(
            f'ResultWriter ready, collecting {self._max_readings} readings '
            f'to {self._output_dir}')

    def write_callback(self, msg):
        self._readings.append({
            'sensor_id': msg.sensor_id,
            'temperature': msg.calibrated_temperature,
            'humidity': msg.calibrated_humidity,
            'pressure': msg.calibrated_pressure,
            'is_valid': msg.is_valid
        })
        self.get_logger().info(
            f'Received reading {len(self._readings)}/{self._max_readings}')

        if len(self._readings) >= self._max_readings:
            self._write_csv()
            raise SystemExit(0)

    def _write_csv(self):
        filepath = os.path.join(self._output_dir, 'results.csv')
        with open(filepath, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'sensor_id', 'temperature', 'humidity',
                'pressure', 'is_valid'])
            writer.writeheader()
            writer.writerows(self._readings)
        self.get_logger().info(
            f'Wrote {len(self._readings)} readings to {filepath}')


def main(args=None):
    rclpy.init(args=args)
    node = ResultWriter()
    try:
        rclpy.spin(node)
    except SystemExit:
        pass
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
