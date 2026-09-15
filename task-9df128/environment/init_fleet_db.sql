-- Fleet operations database for warehouse AGV deployments
-- Contains platform registry, deployment constraints, and incident history

CREATE TABLE platform_registry (
    platform_id TEXT PRIMARY KEY,
    platform_type TEXT NOT NULL,
    motion_model_plugin TEXT NOT NULL,
    bt_template TEXT,
    description TEXT
);

CREATE TABLE deployment_configs (
    config_id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_id TEXT NOT NULL,
    param_path TEXT NOT NULL,
    param_value TEXT NOT NULL,
    constraint_category TEXT NOT NULL,
    notes TEXT,
    FOREIGN KEY (platform_id) REFERENCES platform_registry(platform_id)
);

CREATE TABLE incident_log (
    incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_id TEXT NOT NULL,
    incident_date TEXT NOT NULL,
    severity TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    root_cause TEXT NOT NULL,
    resolution TEXT NOT NULL,
    FOREIGN KEY (platform_id) REFERENCES platform_registry(platform_id)
);

-- Platform registry
INSERT INTO platform_registry VALUES ('WH-DD-001', 'diff_drive', 'mppi::DiffDriveMotionModel', 'navigate_spin_recovery.xml', 'Original warehouse diff-drive robot');
INSERT INTO platform_registry VALUES ('WH-DD-002', 'diff_drive', 'mppi::DiffDriveMotionModel', 'navigate_spin_recovery.xml', 'Secondary diff-drive robot');
INSERT INTO platform_registry VALUES ('WH-ACK-001', 'ackermann', 'mppi::AckermannMotionModel', 'navigate_backup_recovery.xml', 'First Ackermann AGV deployment');
INSERT INTO platform_registry VALUES ('WH-ACK-002', 'ackermann', 'mppi::AckermannMotionModel', 'navigate_backup_recovery.xml', 'Second Ackermann AGV deployment');
INSERT INTO platform_registry VALUES ('WH-OMNI-001', 'omnidirectional', 'mppi::OmniMotionModel', 'navigate_spin_recovery.xml', 'Omnidirectional picking robot');

-- Reference constraints from successful Ackermann deployments
INSERT INTO deployment_configs (platform_id, param_path, param_value, constraint_category, notes)
VALUES ('WH-ACK-001', 'FollowPath.vy_max', '0.0', 'kinematic', 'Non-holonomic: zero lateral motion');
INSERT INTO deployment_configs (platform_id, param_path, param_value, constraint_category, notes)
VALUES ('WH-ACK-001', 'FollowPath.ay_max', '0.0', 'kinematic', 'Zero lateral acceleration for non-holonomic');
INSERT INTO deployment_configs (platform_id, param_path, param_value, constraint_category, notes)
VALUES ('WH-ACK-001', 'FollowPath.ay_min', '0.0', 'kinematic', 'Zero lateral deceleration for non-holonomic');
INSERT INTO deployment_configs (platform_id, param_path, param_value, constraint_category, notes)
VALUES ('WH-ACK-002', 'collision_monitor.cmd_vel_in_topic', 'cmd_vel_smoothed', 'topology', 'Monitor must sit after smoother in velocity pipeline');
INSERT INTO deployment_configs (platform_id, param_path, param_value, constraint_category, notes)
VALUES ('WH-ACK-001', 'local_costmap.rolling_window', 'true', 'costmap', 'Required for odom-frame local costmap');
INSERT INTO deployment_configs (platform_id, param_path, param_value, constraint_category, notes)
VALUES ('WH-ACK-002', 'FollowPath.vy_max', '0.0', 'kinematic', 'Confirmed: must be exactly zero, not small positive');

-- Incident reports from past Ackermann platform migrations
INSERT INTO incident_log (platform_id, incident_date, severity, category, description, root_cause, resolution)
VALUES ('WH-ACK-001', '2024-08-15', 'critical', 'collision',
  'AGV clipped shelf corner during tight aisle turn. Laser scan showed no obstacle detection prior to contact.',
  'Inflation radius was configured using inscribed_radius (0.18m) instead of circumscribed_radius (0.37m). The rectangular robot corners extended beyond the inflated safety zone during turns.',
  'Updated both local and global costmap inflation_radius to values exceeding the circumscribed_radius of the platform.');

INSERT INTO incident_log (platform_id, incident_date, severity, category, description, root_cause, resolution)
VALUES ('WH-ACK-001', '2024-09-22', 'high', 'trajectory_failure',
  'MPPI controller generated trajectories scored as collision-free but extending beyond local costmap boundary, causing unexpected emergency stops.',
  'Local costmap dimensions (3m x 3m) were too small. The MPPI prediction horizon distance exceeded half the costmap width, meaning trajectory endpoints fell outside the scored region and received default zero cost.',
  'Resized local costmap width and height to at least twice the prediction horizon distance (time_steps * model_dt * vx_max).');

INSERT INTO incident_log (platform_id, incident_date, severity, category, description, root_cause, resolution)
VALUES ('WH-ACK-002', '2024-10-01', 'high', 'recovery_failure',
  'AGV entered Spin recovery near dock obstacle but physically could not execute the rotation. Recovery timed out after 30 seconds and mission was aborted.',
  'Behavior tree used Spin as a recovery action. Ackermann-steered vehicles have a nonzero minimum turning radius and cannot rotate in place.',
  'Replaced Spin recovery node with BackUp in the behavior tree. Ackermann vehicles can safely reverse along their current heading.');

INSERT INTO incident_log (platform_id, incident_date, severity, category, description, root_cause, resolution)
VALUES ('WH-ACK-001', '2024-11-10', 'medium', 'cost_threshold',
  'CostCritic triggered collision avoidance at impossible costmap values, causing spurious trajectory rejection in open areas.',
  'near_collision_cost was set to 300, exceeding the valid OccupancyGrid cost range. Values 254 (lethal obstacle) and 255 (unknown space) are reserved sentinel values; valid obstacle proximity costs occupy the range [1, 253].',
  'Set near_collision_cost to 253 to match the maximum valid obstacle proximity cost.');

INSERT INTO incident_log (platform_id, incident_date, severity, category, description, root_cause, resolution)
VALUES ('WH-ACK-002', '2024-12-05', 'high', 'velocity_mismatch',
  'AGV exhibited jerky motion with sudden velocity jumps during corridor navigation. Velocity commands were being clipped asymmetrically by the smoother.',
  'Velocity smoother max_velocity and min_velocity arrays did not match the MPPI controller kinematic limits. The smoother was clipping valid controller outputs while passing through invalid ones.',
  'Synchronized velocity smoother limit arrays to exactly match the controller vx_max, vx_min, and wz_max parameters.');

INSERT INTO incident_log (platform_id, incident_date, severity, category, description, root_cause, resolution)
VALUES ('WH-ACK-001', '2025-01-18', 'medium', 'handoff_glitch',
  'AGV oscillated between path-following and goal-seeking behavior at approximately 3m from goal, causing slow zigzag approach pattern.',
  'GoalCritic and PathFollowCritic threshold_to_consider values were different, creating a transition zone where both critics competed with conflicting objectives. These thresholds should be equal and set near the prediction horizon distance.',
  'Aligned both threshold_to_consider values to equal the prediction horizon distance for clean single-point behavioral handoff.');

INSERT INTO incident_log (platform_id, incident_date, severity, category, description, root_cause, resolution)
VALUES ('WH-ACK-002', '2025-02-28', 'critical', 'costmap_drift',
  'AGV lost obstacle awareness after traveling approximately 15m from start position. All obstacles disappeared from local costmap despite laser scanner functioning correctly.',
  'Local costmap global_frame was set to odom but rolling_window was false. Without rolling window the costmap origin remains fixed at the initial position; the robot drives beyond the costmap boundary.',
  'Enabled rolling_window: true for the local costmap to maintain a robot-centric obstacle view.');
