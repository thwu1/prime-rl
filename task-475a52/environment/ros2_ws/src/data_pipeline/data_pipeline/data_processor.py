import rclpy
from rclpy.lifecycle import LifecycleNode, TransitionCallbackReturn
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs_custom.msg import SensorReading, ProcessedData


class DataProcessor(LifecycleNode):
    def __init__(self):
        super().__init__('data_processor')
        self.declare_parameter('calibration_offset', 0.0)
        self.declare_parameter('calibration_scale', 1.0)
        self._subscription = None
        self._publisher = None
        self._offset = 0.0
        self._scale = 1.0
        self._active = False

    def on_configure(self, state):
        self.get_logger().info('Configuring data_processor...')
        self._offset = self.get_parameter('calibration_offset').value
        self._scale = self.get_parameter('calibration_scale').value

        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )
        self._subscription = self.create_subscription(
            SensorReading, '/sensor/raw', self.process_callback, qos)
        self._publisher = self.create_publisher(
            ProcessedData, '/sensor/processed', qos)

        self.get_logger().info(
            f'data_processor configured: offset={self._offset}, scale={self._scale}')
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state):
        self.get_logger().info('Activating data_processor...')
        self._active = True
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state):
        self.get_logger().info('Deactivating data_processor...')
        self._active = False
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state):
        self.get_logger().info('Cleaning up data_processor...')
        self._active = False
        if self._subscription:
            self.destroy_subscription(self._subscription)
            self._subscription = None
        if self._publisher:
            self.destroy_publisher(self._publisher)
            self._publisher = None
        return TransitionCallbackReturn.SUCCESS

    def process_callback(self, msg):
        if not self._active:
            return

        processed = ProcessedData()
        processed.header = msg.header
        processed.sensor_id = msg.sensor_id
        processed.calibrated_temperature = (
            msg.temperature * self._scale + self._offset)
        processed.calibrated_humidity = (
            msg.humidity * self._scale + self._offset)
        processed.calibrated_pressure = (
            msg.pressure * self._scale + self._offset)
        processed.is_valid = (
            -40.0 <= processed.calibrated_temperature <= 85.0
            and 0.0 <= processed.calibrated_humidity <= 100.0
            and 300.0 <= processed.calibrated_pressure <= 1100.0
        )
        self._publisher.publish(processed)
        self.get_logger().info(
            f'Processed sensor {msg.sensor_id}: '
            f'temp={processed.calibrated_temperature:.2f}')


def main(args=None):
    rclpy.init(args=args)
    node = DataProcessor()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
