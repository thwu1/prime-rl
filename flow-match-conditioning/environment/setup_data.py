import numpy as np
import json
import os

os.makedirs('/app/sample_data', exist_ok=True)

rng = np.random.RandomState(42)
traj = np.zeros((100, 14))
traj[:, :6] = rng.randn(100, 6) * 0.5
traj[:, 6] = np.linspace(0.001, 0.065, 100)
traj[:, 7:13] = rng.randn(100, 6) * 0.5
traj[:, 13] = np.linspace(0.069, 0.001, 100)

np.save('/app/sample_data/trajectory.npy', traj)

episode = {
    'task_description': 'pick up the red block and place it on the blue plate',
    'num_video_frames': 100,
    'episode_id': 'episode_42',
    'cameras': ['cam_high', 'cam_left_wrist', 'cam_right_wrist'],
}

with open('/app/sample_data/episode.json', 'w') as f:
    json.dump(episode, f, indent=2)
