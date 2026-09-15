"""
SimulationEngine — auto-translated from C++ reference backend.
Implements the simulation_interfaces v2.1.0 protocol.

Read /app/idl/messages.idl and /app/idl/services.idl for the
full specification. Each FooBar.srv maps to a foo_bar() method
returning a FooBarResponse dataclass from interfaces.py.

"""
from copy import deepcopy
from typing import Dict, Optional, List
from interfaces import *


class SimulationEngine:
    """Simulation engine implementing the simulation_interfaces v2.1.0 standard."""

    STEP_DT_NANOSEC = 1_000_000       # 1 ms per step
    NANOSEC_PER_SEC = 1_000_000_000

    SUPPORTED_FEATURES = [
        FeatureCode.SPAWNING,
        FeatureCode.DELETING,
        FeatureCode.ENTITY_TAGS,
        FeatureCode.ENTITY_CATEGORIES,
        FeatureCode.SPAWNING_RESOURCE_STRING,
        FeatureCode.ENTITY_STATE_GETTING,
        FeatureCode.ENTITY_STATE_SETTING,
        FeatureCode.ENTITY_INFO_GETTING,
        FeatureCode.ENTITY_INFO_SETTING,
        FeatureCode.SIMULATION_RESET,
        FeatureCode.SIMULATION_RESET_TIME,
        FeatureCode.SIMULATION_RESET_STATE,
        FeatureCode.SIMULATION_RESET_SPAWNED,
        FeatureCode.SIMULATION_STATE_GETTING,
        FeatureCode.SIMULATION_STATE_SETTING,
        FeatureCode.SIMULATION_STATE_PAUSE,
        FeatureCode.STEP_SIMULATION_SINGLE,
        FeatureCode.STEP_SIMULATION_MULTIPLE,
        FeatureCode.WORLD_LOADING,
        FeatureCode.WORLD_UNLOADING,
        FeatureCode.WORLD_INFO_GETTING,
        FeatureCode.SPAWNING_ENTITIES,
    ]

    VALID_TRANSITIONS = {
        SimStateCode.STOPPED: {SimStateCode.PLAYING},
        SimStateCode.PLAYING: {SimStateCode.PAUSED, SimStateCode.STOPPED},
        SimStateCode.PAUSED:  {SimStateCode.PLAYING, SimStateCode.STOPPED},
    }

    def __init__(self):
        self._sim_state: int = SimStateCode.NO_WORLD
        self._world: Optional[WorldResource] = None
        self._entities: Dict[str, dict] = {}
        self._sim_time_nanosec: int = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _has_world(self) -> bool:
        return self._sim_state in (
            SimStateCode.STOPPED, SimStateCode.PLAYING, SimStateCode.PAUSED)

    def _make_header(self) -> Header:
        sec = self._sim_time_nanosec // self.NANOSEC_PER_SEC
        nsec = self._sim_time_nanosec % self.NANOSEC_PER_SEC
        return Header(stamp_sec=sec, stamp_nanosec=nsec)

    def _entity_matches(self, name: str, record: dict,
                        filters: EntityFilters) -> bool:
        if filters.filter and filters.filter not in name:
            return False
        if filters.categories:
            entity_cat = record["info"].category.category
            allowed = {c.category for c in filters.categories}
            if entity_cat not in allowed:
                return False
        if filters.tags.tags:
            entity_tags = set(record["info"].tags)
            filter_tags = set(filters.tags.tags)
            if filters.tags.filter_mode == TagsFilter.FILTER_MODE_ANY:
                if not filter_tags.issubset(entity_tags):
                    return False
            elif filters.tags.filter_mode == TagsFilter.FILTER_MODE_ALL:
                if not entity_tags & filter_tags:
                    return False
        if (filters.bounds.type == Bounds.TYPE_BOX
                and len(filters.bounds.points) >= 2):
            pos = record["state"].pose.position
            mn = filters.bounds.points[0]
            mx = filters.bounds.points[1]
            if not (mn.x <= pos.x < mx.x
                    and mn.y <= pos.y < mx.y
                    and mn.z <= pos.z < mx.z):
                return False
        return True

    # ------------------------------------------------------------------
    # Service implementations
    # ------------------------------------------------------------------

    def get_simulator_features(self) -> GetSimulatorFeaturesResponse:
        return GetSimulatorFeaturesResponse(
            features=SimulatorFeatures(
                features=list(self.SUPPORTED_FEATURES),
                spawn_formats=["sdf", "urdf"],
            )
        )

    def load_world(self, world_resource: Resource,
                   fail_on_unsupported_element: bool = False,
                   ignore_missing_or_unsupported_assets: bool = False
                   ) -> LoadWorldResponse:
        if self._sim_state != SimStateCode.NO_WORLD:
            return LoadWorldResponse(
                result=Result(ResultCode.INCORRECT_STATE))
        if not world_resource.uri and not world_resource.resource_string:
            return LoadWorldResponse(
                result=Result(LoadWorldError.NO_RESOURCE))

        world = WorldResource(
            name=world_resource.uri or "world",
            world_resource=deepcopy(world_resource),
        )
        self._world = world
        self._sim_state = SimStateCode.STOPPED
        self._entities.clear()

        return LoadWorldResponse(
            result=Result(ResultCode.OK),
            world=deepcopy(world),
        )

    def unload_world(self) -> UnloadWorldResponse:
        if not self._has_world():
            return UnloadWorldResponse(
                result=Result(UnloadWorldError.NO_WORLD_LOADED))
        self._world = None
        self._sim_state = SimStateCode.NO_WORLD
        self._entities.clear()
        return UnloadWorldResponse(result=Result(ResultCode.OK))

    def get_current_world(self) -> GetCurrentWorldResponse:
        if not self._has_world() or self._world is None:
            return GetCurrentWorldResponse(
                result=Result(GetCurrentWorldError.NO_WORLD_LOADED))
        return GetCurrentWorldResponse(
            result=Result(ResultCode.OK),
            world=deepcopy(self._world),
        )

    def spawn_entity(self, name: str, entity_resource: Resource,
                     allow_renaming: bool = False,
                     initial_pose: PoseStamped = None,
                     entity_namespace: str = "",
                     ) -> SpawnEntityResponse:
        # State check
        if not self._has_world():
            return SpawnEntityResponse(
                result=Result(ResultCode.INCORRECT_STATE),
                entity_name=name)
        # Name validation
        if not name:
            return SpawnEntityResponse(
                result=Result(SpawnErrorCode.NAME_INVALID),
                entity_name=name)
        # Resource presence
        if not entity_resource.uri and not entity_resource.resource_string:
            return SpawnEntityResponse(
                result=Result(SpawnErrorCode.NO_RESOURCE),
                entity_name=name)
        # Name uniqueness (checked before any resource content validation)
        actual_name = name
        if actual_name in self._entities:
            if not allow_renaming:
                return SpawnEntityResponse(
                    result=Result(SpawnErrorCode.NAME_NOT_UNIQUE),
                    entity_name=name)
            i = 1
            while f"{name}_{i}" in self._entities:
                i += 1
            actual_name = f"{name}_{i}"

        state = EntityState(header=self._make_header())
        if initial_pose is not None:
            state.pose = deepcopy(initial_pose.pose)

        self._entities[actual_name] = {
            "state": state,
            "info": EntityInfo(),
            "initial_state": deepcopy(state),
        }

        return SpawnEntityResponse(
            result=Result(ResultCode.OK),
            entity_name=actual_name,
        )

    def spawn_entities(self, spawn_requests: list) -> SpawnEntitiesResponse:
        if not self._has_world():
            return SpawnEntitiesResponse(
                result=Result(ResultCode.INCORRECT_STATE))

        results: List[SpawnResult] = []
        any_failed = False

        for req in spawn_requests:
            r = self.spawn_entity(
                name=req.name,
                entity_resource=req.entity_resource,
                allow_renaming=req.allow_renaming,
                initial_pose=req.initial_pose,
            )
            results.append(SpawnResult(
                result=deepcopy(r.result),
                entity_name=r.entity_name,
            ))
            if r.result.result != ResultCode.OK:
                any_failed = True

        overall = Result(ResultCode.OK)
        if any_failed:
            overall = Result(SpawnEntitiesError.ENTITIES_SPAWN_FAILED)

        return SpawnEntitiesResponse(result=overall, results=results)

    def delete_entity(self, entity_name: str) -> DeleteEntityResponse:
        if not self._has_world():
            return DeleteEntityResponse(
                result=Result(ResultCode.INCORRECT_STATE))
        if entity_name not in self._entities:
            return DeleteEntityResponse(
                result=Result(ResultCode.NOT_FOUND))
        del self._entities[entity_name]
        return DeleteEntityResponse(result=Result(ResultCode.OK))

    def get_entities(self, filters: EntityFilters = None
                     ) -> GetEntitiesResponse:
        if not self._has_world():
            return GetEntitiesResponse(
                result=Result(ResultCode.INCORRECT_STATE))
        if filters is None:
            filters = EntityFilters()

        matching = [
            name for name, record in self._entities.items()
            if self._entity_matches(name, record, filters)
        ]
        return GetEntitiesResponse(
            result=Result(ResultCode.OK), entities=matching)

    def get_entity_state(self, entity_name: str) -> GetEntityStateResponse:
        if entity_name not in self._entities:
            return GetEntityStateResponse(
                result=Result(ResultCode.NOT_FOUND))
        state = deepcopy(self._entities[entity_name]["state"])
        state.header = self._make_header()
        return GetEntityStateResponse(
            result=Result(ResultCode.OK), state=state)

    def set_entity_state(self, entity_name: str, state: EntityState,
                         set_pose: bool = True, set_twist: bool = True,
                         set_acceleration: bool = True
                         ) -> SetEntityStateResponse:
        if entity_name not in self._entities:
            return SetEntityStateResponse(
                result=Result(ResultCode.NOT_FOUND))

        current = self._entities[entity_name]["state"]
        if set_pose:
            current.pose = state.pose
        if set_twist:
            current.twist = state.twist
        if set_acceleration:
            current.acceleration = state.acceleration

        return SetEntityStateResponse(result=Result(ResultCode.OK))

    def get_entity_info(self, entity_name: str) -> GetEntityInfoResponse:
        if entity_name not in self._entities:
            return GetEntityInfoResponse(
                result=Result(ResultCode.NOT_FOUND))
        return GetEntityInfoResponse(
            result=Result(ResultCode.OK),
            info=deepcopy(self._entities[entity_name]["info"]))

    def set_entity_info(self, entity_name: str, info: EntityInfo
                        ) -> SetEntityInfoResponse:
        if entity_name not in self._entities:
            return SetEntityInfoResponse(
                result=Result(ResultCode.NOT_FOUND))
        self._entities[entity_name]["info"] = deepcopy(info)
        return SetEntityInfoResponse(result=Result(ResultCode.OK))

    def get_simulation_state(self) -> GetSimulationStateResponse:
        return GetSimulationStateResponse(
            state=SimulationState(self._sim_state),
            result=Result(ResultCode.OK))

    def set_simulation_state(self, target: SimulationState
                             ) -> SetSimulationStateResponse:
        ts = target.state

        # Validate target is a settable state
        if ts not in (SimStateCode.STOPPED, SimStateCode.PLAYING,
                      SimStateCode.PAUSED):
            return SetSimulationStateResponse(
                result=Result(SetSimStateError.INCORRECT_TRANSITION))

        if not self._has_world():
            return SetSimulationStateResponse(
                result=Result(ResultCode.INCORRECT_STATE))

        if ts == self._sim_state:
            return SetSimulationStateResponse(
                result=Result(SetSimStateError.ALREADY_IN_TARGET_STATE))

        valid_targets = self.VALID_TRANSITIONS.get(self._sim_state, set())
        if ts not in valid_targets:
            return SetSimulationStateResponse(
                result=Result(SetSimStateError.INCORRECT_TRANSITION))

        self._sim_state = ts
        return SetSimulationStateResponse(result=Result(ResultCode.OK))

    def step_simulation(self, steps: int = 1) -> StepSimulationResponse:
        if self._sim_state != SimStateCode.PAUSED:
            return StepSimulationResponse(
                result=Result(ResultCode.INCORRECT_STATE))
        self._sim_time_nanosec += steps * self.STEP_DT_NANOSEC
        return StepSimulationResponse(result=Result(ResultCode.OK))

    def reset_simulation(self, scope: int = ResetScope.DEFAULT
                         ) -> ResetSimulationResponse:
        if not self._has_world():
            return ResetSimulationResponse(
                result=Result(ResultCode.INCORRECT_STATE))

        if scope == ResetScope.DEFAULT:
            scope = ResetScope.ALL

        if scope & ResetScope.TIME:
            self._sim_time_nanosec = 0

        if scope & ResetScope.STATE:
            for record in self._entities.values():
                record["state"] = deepcopy(record["initial_state"])
        elif scope & ResetScope.SPAWNED:
            self._entities.clear()

        return ResetSimulationResponse(result=Result(ResultCode.OK))
