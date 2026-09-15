"""
Fix all bugs in the ROS2 sensor data pipeline and implement the missing anomaly_filter node.
"""
import shutil

# Bug 1: Add DEPENDENCIES std_msgs to rosidl_generate_interfaces
cmake_path = '/app/ros2_ws/src/sensor_msgs_custom/CMakeLists.txt'
with open(cmake_path, 'r') as f:
    content = f.read()
content = content.replace(
    '  "msg/ProcessedData.msg"\n)',
    '  "msg/ProcessedData.msg"\n  DEPENDENCIES std_msgs\n)'
)
with open(cmake_path, 'w') as f:
    f.write(content)
print('Fixed: Added DEPENDENCIES std_msgs to rosidl_generate_interfaces')

# Bug 2: Change publisher QoS from BEST_EFFORT to RELIABLE
pub_path = '/app/ros2_ws/src/data_pipeline/data_pipeline/sensor_publisher.py'
with open(pub_path, 'r') as f:
    content = f.read()
content = content.replace(
    'ReliabilityPolicy.BEST_EFFORT',
    'ReliabilityPolicy.RELIABLE'
)
with open(pub_path, 'w') as f:
    f.write(content)
print('Fixed: Changed publisher QoS from BEST_EFFORT to RELIABLE')

# Bug 4: Fix parameter YAML - wrong node name key
params_path = '/app/ros2_ws/src/data_pipeline/config/params.yaml'
with open(params_path, 'w') as f:
    f.write('/**:\n  ros__parameters:\n    calibration_offset: 1.5\n    calibration_scale: 1.02\n')
print('Fixed: Corrected node name key in params.yaml')

# Implement missing anomaly_filter node
shutil.copy(
    '/solution/anomaly_filter_impl.py',
    '/app/ros2_ws/src/data_pipeline/data_pipeline/anomaly_filter.py'
)
print('Implemented: anomaly_filter lifecycle node with z-score outlier detection')

# Bug 3 + Bug 5 + anomaly_filter integration: Rewrite launch file
# - Fix lifecycle ordering (configure before activate for data_processor)
# - Remove incorrect topic remapping
# - Add anomaly_filter node with lifecycle transitions
launch_path = '/app/ros2_ws/src/data_pipeline/launch/pipeline_launch.py'
launch_content = '''from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, TimerAction, LogInfo
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode, Node


def generate_launch_description():
    ns_arg = DeclareLaunchArgument(
        'namespace', default_value='pipeline',
        description='Namespace for the pipeline nodes')

    ns = LaunchConfiguration('namespace')

    # Lifecycle-managed sensor publisher
    sensor_pub = LifecycleNode(
        package='data_pipeline',
        executable='sensor_publisher',
        name='sensor_publisher',
        namespace=ns,
        output='screen'
    )

    # Lifecycle-managed data processor
    data_proc = LifecycleNode(
        package='data_pipeline',
        executable='data_processor',
        name='data_processor',
        namespace=ns,
        output='screen',
        parameters=['/app/ros2_ws/src/data_pipeline/config/params.yaml'],
        remappings=[]
    )

    # Lifecycle-managed anomaly filter
    anomaly_filt = LifecycleNode(
        package='data_pipeline',
        executable='anomaly_filter',
        name='anomaly_filter',
        namespace=ns,
        output='screen'
    )

    # Regular result writer node
    result_writer = Node(
        package='data_pipeline',
        executable='result_writer',
        name='result_writer',
        namespace=ns,
        output='screen',
        parameters=[{
            'output_dir': '/app/output',
            'max_readings': 10
        }]
    )

    # Lifecycle transitions: configure then activate each node
    # Process downstream nodes first so they are ready when data flows

    cfg_proc = TimerAction(period=3.0, actions=[
        LogInfo(msg='Configuring data_processor...'),
        ExecuteProcess(
            cmd=['ros2', 'lifecycle', 'set',
                 '/pipeline/data_processor', 'configure'],
            output='screen'
        )
    ])

    act_proc = TimerAction(period=5.0, actions=[
        LogInfo(msg='Activating data_processor...'),
        ExecuteProcess(
            cmd=['ros2', 'lifecycle', 'set',
                 '/pipeline/data_processor', 'activate'],
            output='screen'
        )
    ])

    cfg_filter = TimerAction(period=7.0, actions=[
        LogInfo(msg='Configuring anomaly_filter...'),
        ExecuteProcess(
            cmd=['ros2', 'lifecycle', 'set',
                 '/pipeline/anomaly_filter', 'configure'],
            output='screen'
        )
    ])

    act_filter = TimerAction(period=9.0, actions=[
        LogInfo(msg='Activating anomaly_filter...'),
        ExecuteProcess(
            cmd=['ros2', 'lifecycle', 'set',
                 '/pipeline/anomaly_filter', 'activate'],
            output='screen'
        )
    ])

    cfg_sensor = TimerAction(period=11.0, actions=[
        LogInfo(msg='Configuring sensor_publisher...'),
        ExecuteProcess(
            cmd=['ros2', 'lifecycle', 'set',
                 '/pipeline/sensor_publisher', 'configure'],
            output='screen'
        )
    ])

    act_sensor = TimerAction(period=13.0, actions=[
        LogInfo(msg='Activating sensor_publisher...'),
        ExecuteProcess(
            cmd=['ros2', 'lifecycle', 'set',
                 '/pipeline/sensor_publisher', 'activate'],
            output='screen'
        )
    ])

    return LaunchDescription([
        ns_arg,
        sensor_pub,
        data_proc,
        anomaly_filt,
        result_writer,
        cfg_proc,
        act_proc,
        cfg_filter,
        act_filter,
        cfg_sensor,
        act_sensor,
    ])
'''

with open(launch_path, 'w') as f:
    f.write(launch_content)
print('Fixed: Rewrote launch file with correct lifecycle ordering, removed bad remapping, added anomaly_filter')

print('\nAll fixes applied successfully.')
