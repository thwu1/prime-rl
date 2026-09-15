import rclpy
from rclpy.lifecycle import LifecycleNode, TransitionCallbackReturn
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs_custom.msg import ProcessedData
import math
from collections import deque


class AnomalyFilter(LifecycleNode):
    """Lifecycle-managed anomaly filter that performs z-score based outlier detection."""

    def __init__(self):
        super().__init__('anomaly_filter')
        self.declare_parameter('window_size', 20)
        self.declare_parameter('z_threshold', 3.0)
        self._subscription = None
        self._publisher = None
        self._active = False
        self._window_size = 20
        self._z_threshold = 3.0
        self._temp_window = deque()
        self._humidity_window = deque()
        self._pressure_window = deque()
        self._received_count = 0
        self._forwarded_count = 0
        self._dropped_count = 0

    def on_configure(self, state):
        self.get_logger().info('Configuring anomaly_filter...')
        self._window_size = self.get_parameter('window_size').value
        self._z_threshold = self.get_parameter('z_threshold').value

        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )
        self._subscription = self.create_subscription(
            ProcessedData, '/sensor/processed', self.filter_callback, qos)
        self._publisher = self.create_publisher(
            ProcessedData, '/sensor/filtered', qos)

        self._temp_window = deque(maxlen=self._window_size)
        self._humidity_window = deque(maxlen=self._window_size)
        self._pressure_window = deque(maxlen=self._window_size)
        self._received_count = 0
        self._forwarded_count = 0
        self._dropped_count = 0

        self.get_logger().info(
            f'anomaly_filter configured: window_size={self._window_size}, '
            f'z_threshold={self._z_threshold}')
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state):
        self.get_logger().info('Activating anomaly_filter...')
        self._active = True
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state):
        self.get_logger().info('Deactivating anomaly_filter...')
        self._active = False
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state):
        self.get_logger().info('Cleaning up anomaly_filter...')
        self._active = False
        if self._subscription:
            self.destroy_subscription(self._subscription)
            self._subscription = None
        if self._publisher:
            self.destroy_publisher(self._publisher)
            self._publisher = None
        self._temp_window.clear()
        self._humidity_window.clear()
        self._pressure_window.clear()
        return TransitionCallbackReturn.SUCCESS

    def _compute_mean(self, window):
        if len(window) == 0:
            return 0.0
        return sum(window) / len(window)

    def _compute_std_deviation(self, window, mean):
        if len(window) < 2:
            return 0.0
        variance = sum((x - mean) ** 2 for x in window) / len(window)
        return math.sqrt(variance) if variance > 0 else 0.0

    def _compute_z_score(self, value, window):
        if len(window) < 2:
            return 0.0
        mean = self._compute_mean(window)
        std = self._compute_std_deviation(window, mean)
        if std == 0.0:
            return 0.0
        return abs(value - mean) / std

    def filter_callback(self, msg):
        if not self._active:
            return

        self._received_count += 1

        # During warmup period, forward all readings (insufficient data for statistics)
        warmup = len(self._temp_window) < self._window_size

        is_outlier = False
        if not warmup:
            z_temp = self._compute_z_score(
                msg.calibrated_temperature, self._temp_window)
            z_humidity = self._compute_z_score(
                msg.calibrated_humidity, self._humidity_window)
            z_pressure = self._compute_z_score(
                msg.calibrated_pressure, self._pressure_window)

            if (z_temp > self._z_threshold
                    or z_humidity > self._z_threshold
                    or z_pressure > self._z_threshold):
                is_outlier = True
                self._dropped_count += 1
                self.get_logger().warn(
                    f'Outlier detected (reading #{self._received_count}): '
                    f'z_scores=({z_temp:.2f}, {z_humidity:.2f}, {z_pressure:.2f})')

        # Update sliding windows with current reading
        self._temp_window.append(msg.calibrated_temperature)
        self._humidity_window.append(msg.calibrated_humidity)
        self._pressure_window.append(msg.calibrated_pressure)

        if not is_outlier:
            self._publisher.publish(msg)
            self._forwarded_count += 1
            self.get_logger().info(
                f'Forwarded reading #{self._forwarded_count} '
                f'(sensor {msg.sensor_id}, '
                f'warmup={warmup})')


def main(args=None):
    rclpy.init(args=args)
    node = AnomalyFilter()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
