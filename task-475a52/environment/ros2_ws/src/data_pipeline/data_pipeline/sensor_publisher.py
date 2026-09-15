import rclpy
from rclpy.lifecycle import LifecycleNode, TransitionCallbackReturn
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs_custom.msg import SensorReading
import math


class SensorPublisher(LifecycleNode):
    def __init__(self):
        super().__init__('sensor_publisher')
        self._publisher = None
        self._timer = None
        self._count = 0

    def on_configure(self, state):
        self.get_logger().info('Configuring sensor_publisher...')
        qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )
        self._publisher = self.create_publisher(
            SensorReading, '/sensor/raw', qos)
        self.get_logger().info('sensor_publisher configured.')
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state):
        self.get_logger().info('Activating sensor_publisher...')
        self._timer = self.create_timer(0.5, self.timer_callback)
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state):
        self.get_logger().info('Deactivating sensor_publisher...')
        if self._timer:
            self.destroy_timer(self._timer)
            self._timer = None
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state):
        self.get_logger().info('Cleaning up sensor_publisher...')
        if self._publisher:
            self.destroy_publisher(self._publisher)
            self._publisher = None
        return TransitionCallbackReturn.SUCCESS

    def timer_callback(self):
        msg = SensorReading()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.sensor_id = 1
        msg.temperature = 20.0 + 5.0 * math.sin(self._count * 0.1)
        msg.humidity = 45.0 + 10.0 * math.cos(self._count * 0.1)
        msg.pressure = 1013.25 + 2.0 * math.sin(self._count * 0.05)
        self._publisher.publish(msg)
        self.get_logger().info(f'Published reading #{self._count}')
        self._count += 1


def main(args=None):
    rclpy.init(args=args)
    node = SensorPublisher()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
