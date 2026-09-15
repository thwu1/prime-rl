import os
from glob import glob
from setuptools import setup

package_name = 'data_pipeline'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'),
            glob(os.path.join('launch', '*.py'))),
        (os.path.join('share', package_name, 'config'),
            glob(os.path.join('config', '*.yaml'))),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='developer',
    maintainer_email='dev@example.com',
    description='Sensor data processing pipeline',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'sensor_publisher = data_pipeline.sensor_publisher:main',
            'data_processor = data_pipeline.data_processor:main',
            'anomaly_filter = data_pipeline.anomaly_filter:main',
            'result_writer = data_pipeline.result_writer:main',
        ],
    },
)
