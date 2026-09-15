"""
simulation_interfaces v2.1.0 — Python dataclass definitions.
Mirrors the ros-simulation/simulation_interfaces ROS 2 IDL.

"""
from dataclasses import dataclass, field
from typing import List, Optional

# ============================================================
# Geometry primitives (mirrors geometry_msgs)
# ============================================================

@dataclass
class Vector3:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

@dataclass
class Quaternion:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    w: float = 1.0

@dataclass
class Pose:
    position: Vector3 = field(default_factory=Vector3)
    orientation: Quaternion = field(default_factory=Quaternion)

@dataclass
class Twist:
    linear: Vector3 = field(default_factory=Vector3)
    angular: Vector3 = field(default_factory=Vector3)

@dataclass
class Accel:
    linear: Vector3 = field(default_factory=Vector3)
    angular: Vector3 = field(default_factory=Vector3)

@dataclass
class Header:
    stamp_sec: int = 0
    stamp_nanosec: int = 0
    frame_id: str = ""

@dataclass
class PoseStamped:
    header: Header = field(default_factory=Header)
    pose: Pose = field(default_factory=Pose)


# ============================================================
# Result codes (Result.msg)
# ============================================================

class ResultCode:
    FEATURE_UNSUPPORTED = 0
    OK = 1
    NOT_FOUND = 2
    INCORRECT_STATE = 3
    OPERATION_FAILED = 4

@dataclass
class Result:
    result: int = ResultCode.OK
    error_message: str = ""


# ============================================================
# Entity types
# ============================================================

class CategoryCode:
    OBJECT = 0
    ROBOT = 1
    HUMAN = 2
    DYNAMIC_OBJECT = 4
    STATIC_OBJECT = 5

@dataclass
class EntityCategory:
    category: int = CategoryCode.OBJECT

@dataclass
class TagsFilter:
    FILTER_MODE_ANY = 0
    FILTER_MODE_ALL = 1
    tags: List[str] = field(default_factory=list)
    filter_mode: int = 0

@dataclass
class Bounds:
    TYPE_EMPTY = 0
    TYPE_BOX = 1
    TYPE_CONVEX_HULL = 2
    TYPE_SPHERE = 3
    type: int = 0
    points: List[Vector3] = field(default_factory=list)

@dataclass
class EntityFilters:
    filter: str = ""
    categories: List[EntityCategory] = field(default_factory=list)
    tags: TagsFilter = field(default_factory=TagsFilter)
    bounds: Bounds = field(default_factory=Bounds)

@dataclass
class EntityInfo:
    category: EntityCategory = field(default_factory=EntityCategory)
    description: str = ""
    tags: List[str] = field(default_factory=list)

@dataclass
class EntityState:
    header: Header = field(default_factory=Header)
    pose: Pose = field(default_factory=Pose)
    twist: Twist = field(default_factory=Twist)
    acceleration: Accel = field(default_factory=Accel)


# ============================================================
# Simulation state (SimulationState.msg)
# ============================================================

class SimStateCode:
    STOPPED = 0
    PLAYING = 1
    PAUSED = 2
    QUITTING = 3
    NO_WORLD = 4
    LOADING_WORLD = 5

@dataclass
class SimulationState:
    state: int = SimStateCode.NO_WORLD


# ============================================================
# Feature codes (SimulatorFeatures.msg)
# ============================================================

class FeatureCode:
    SPAWNING = 0
    DELETING = 1
    NAMED_POSES = 2
    POSE_BOUNDS = 3
    ENTITY_TAGS = 4
    ENTITY_BOUNDS = 5
    ENTITY_BOUNDS_BOX = 6
    ENTITY_BOUNDS_CONVEX = 7
    ENTITY_CATEGORIES = 8
    SPAWNING_RESOURCE_STRING = 9
    ENTITY_STATE_GETTING = 10
    ENTITY_STATE_SETTING = 11
    ENTITY_INFO_GETTING = 12
    ENTITY_INFO_SETTING = 13
    SPAWNABLES = 14
    SIMULATION_RESET = 20
    SIMULATION_RESET_TIME = 21
    SIMULATION_RESET_STATE = 22
    SIMULATION_RESET_SPAWNED = 23
    SIMULATION_STATE_GETTING = 24
    SIMULATION_STATE_SETTING = 25
    SIMULATION_STATE_PAUSE = 26
    STEP_SIMULATION_SINGLE = 31
    STEP_SIMULATION_MULTIPLE = 32
    STEP_SIMULATION_ACTION = 33
    WORLD_LOADING = 40
    WORLD_RESOURCE_STRING = 41
    WORLD_TAGS = 42
    WORLD_UNLOADING = 43
    WORLD_INFO_GETTING = 44
    AVAILABLE_WORLDS = 45
    SPAWNING_ENTITIES = 50

@dataclass
class SimulatorFeatures:
    features: List[int] = field(default_factory=list)
    spawn_formats: List[str] = field(default_factory=list)
    custom_info: str = ""


# ============================================================
# Resource types
# ============================================================

@dataclass
class Resource:
    uri: str = ""
    resource_string: str = ""

@dataclass
class WorldResource:
    name: str = ""
    world_resource: Resource = field(default_factory=Resource)
    description: str = ""
    tags: List[str] = field(default_factory=list)


# ============================================================
# Spawn types
# ============================================================

class SpawnErrorCode:
    NAME_NOT_UNIQUE = 101
    NAME_INVALID = 102
    UNSUPPORTED_FORMAT = 103
    NO_RESOURCE = 104
    NAMESPACE_INVALID = 105
    RESOURCE_PARSE_ERROR = 106
    MISSING_ASSETS = 107
    UNSUPPORTED_ASSETS = 108
    INVALID_POSE = 109

@dataclass
class SpawnEntityMsg:
    name: str = ""
    allow_renaming: bool = False
    entity_resource: Resource = field(default_factory=Resource)
    entity_namespace: str = ""
    initial_pose: PoseStamped = field(default_factory=PoseStamped)

@dataclass
class SpawnResult:
    result: Result = field(default_factory=Result)
    entity_name: str = ""


# ============================================================
# Reset scopes (bitwise flags)
# ============================================================

class ResetScope:
    DEFAULT = 0
    TIME = 1
    STATE = 2
    SPAWNED = 4
    ALL = 255


# ============================================================
# Service-specific error codes
# ============================================================

class SetSimStateError:
    ALREADY_IN_TARGET_STATE = 101
    STATE_TRANSITION_ERROR = 102
    INCORRECT_TRANSITION = 103

class LoadWorldError:
    UNSUPPORTED_FORMAT = 101
    NO_RESOURCE = 102
    RESOURCE_PARSE_ERROR = 103
    MISSING_ASSETS = 104
    UNSUPPORTED_ASSETS = 105
    UNSUPPORTED_ELEMENTS = 106

class UnloadWorldError:
    NO_WORLD_LOADED = 101

class GetCurrentWorldError:
    NO_WORLD_LOADED = 101

class SpawnEntitiesError:
    ENTITIES_SPAWN_FAILED = 150

class SetEntityStateError:
    INVALID_POSE = 101


# ============================================================
# Service response types
# ============================================================

@dataclass
class GetSimulatorFeaturesResponse:
    features: SimulatorFeatures = field(default_factory=SimulatorFeatures)

@dataclass
class LoadWorldResponse:
    result: Result = field(default_factory=Result)
    world: WorldResource = field(default_factory=WorldResource)

@dataclass
class UnloadWorldResponse:
    result: Result = field(default_factory=Result)

@dataclass
class GetCurrentWorldResponse:
    result: Result = field(default_factory=Result)
    world: WorldResource = field(default_factory=WorldResource)

@dataclass
class SpawnEntityResponse:
    result: Result = field(default_factory=Result)
    entity_name: str = ""

@dataclass
class SpawnEntitiesResponse:
    result: Result = field(default_factory=Result)
    results: List[SpawnResult] = field(default_factory=list)

@dataclass
class DeleteEntityResponse:
    result: Result = field(default_factory=Result)

@dataclass
class GetEntitiesResponse:
    result: Result = field(default_factory=Result)
    entities: List[str] = field(default_factory=list)

@dataclass
class GetEntityStateResponse:
    result: Result = field(default_factory=Result)
    state: EntityState = field(default_factory=EntityState)

@dataclass
class SetEntityStateResponse:
    result: Result = field(default_factory=Result)

@dataclass
class GetEntityInfoResponse:
    result: Result = field(default_factory=Result)
    info: EntityInfo = field(default_factory=EntityInfo)

@dataclass
class SetEntityInfoResponse:
    result: Result = field(default_factory=Result)

@dataclass
class GetSimulationStateResponse:
    state: SimulationState = field(default_factory=SimulationState)
    result: Result = field(default_factory=Result)

@dataclass
class SetSimulationStateResponse:
    result: Result = field(default_factory=Result)

@dataclass
class StepSimulationResponse:
    result: Result = field(default_factory=Result)

@dataclass
class ResetSimulationResponse:
    result: Result = field(default_factory=Result)
