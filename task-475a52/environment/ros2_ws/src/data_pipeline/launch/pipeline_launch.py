from launch import LaunchDescription
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
        remappings=[('/sensor/processed', '/sensor/calibrated')]
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

    # Lifecycle management via timed CLI commands
    # Data processor lifecycle transitions
    act_proc = TimerAction(period=3.0, actions=[
        LogInfo(msg='Attempting to activate data_processor...'),
        ExecuteProcess(
            cmd=['ros2', 'lifecycle', 'set',
                 '/pipeline/data_processor', 'activate'],
            output='screen'
        )
    ])

    cfg_proc = TimerAction(period=5.0, actions=[
        LogInfo(msg='Attempting to configure data_processor...'),
        ExecuteProcess(
            cmd=['ros2', 'lifecycle', 'set',
                 '/pipeline/data_processor', 'configure'],
            output='screen'
        )
    ])

    # Sensor publisher lifecycle transitions
    cfg_sensor = TimerAction(period=7.0, actions=[
        LogInfo(msg='Configuring sensor_publisher...'),
        ExecuteProcess(
            cmd=['ros2', 'lifecycle', 'set',
                 '/pipeline/sensor_publisher', 'configure'],
            output='screen'
        )
    ])

    act_sensor = TimerAction(period=9.0, actions=[
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
        result_writer,
        act_proc,
        cfg_proc,
        cfg_sensor,
        act_sensor,
    ])
