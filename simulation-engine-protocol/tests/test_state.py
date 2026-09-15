"""
Tests for SimulationEngine — simulation_interfaces v2.1.0 compliance.

"""
import sys
sys.path.insert(0, "/app")

import pytest
from copy import deepcopy
from interfaces import *
from engine import SimulationEngine


@pytest.fixture
def engine():
    return SimulationEngine()


@pytest.fixture
def engine_with_world(engine):
    """Engine with a world loaded (in STOPPED state)."""
    engine.load_world(Resource(uri="file:///worlds/test.sdf"))
    return engine


@pytest.fixture
def engine_playing(engine_with_world):
    """Engine in PLAYING state."""
    engine_with_world.set_simulation_state(SimulationState(SimStateCode.PLAYING))
    return engine_with_world


@pytest.fixture
def engine_paused(engine_playing):
    """Engine in PAUSED state."""
    engine_playing.set_simulation_state(SimulationState(SimStateCode.PAUSED))
    return engine_playing


# ============================================================
# Test: Initial state
# ============================================================

class TestInitialState:
    def test_starts_in_no_world(self, engine):
        resp = engine.get_simulation_state()
        assert resp.state.state == SimStateCode.NO_WORLD
        assert resp.result.result == ResultCode.OK

    def test_features_available(self, engine):
        resp = engine.get_simulator_features()
        feats = resp.features.features
        assert FeatureCode.SPAWNING in feats
        assert FeatureCode.DELETING in feats
        assert FeatureCode.ENTITY_STATE_GETTING in feats
        assert FeatureCode.ENTITY_STATE_SETTING in feats
        assert FeatureCode.ENTITY_INFO_GETTING in feats
        assert FeatureCode.ENTITY_INFO_SETTING in feats
        assert FeatureCode.SIMULATION_STATE_GETTING in feats
        assert FeatureCode.SIMULATION_STATE_SETTING in feats
        assert FeatureCode.SIMULATION_STATE_PAUSE in feats
        assert FeatureCode.STEP_SIMULATION_SINGLE in feats
        assert FeatureCode.STEP_SIMULATION_MULTIPLE in feats
        assert FeatureCode.WORLD_LOADING in feats
        assert FeatureCode.WORLD_UNLOADING in feats
        assert FeatureCode.SIMULATION_RESET in feats
        assert FeatureCode.SPAWNING_ENTITIES in feats
        assert FeatureCode.ENTITY_TAGS in feats
        assert FeatureCode.ENTITY_CATEGORIES in feats

    def test_spawn_formats(self, engine):
        resp = engine.get_simulator_features()
        assert "sdf" in resp.features.spawn_formats
        assert "urdf" in resp.features.spawn_formats


# ============================================================
# Test: World lifecycle
# ============================================================

class TestWorldLifecycle:
    def test_load_world(self, engine):
        resp = engine.load_world(Resource(uri="file:///worlds/test.sdf"))
        assert resp.result.result == ResultCode.OK
        assert resp.world.world_resource.uri == "file:///worlds/test.sdf"
        state = engine.get_simulation_state()
        assert state.state.state == SimStateCode.STOPPED

    def test_load_world_no_resource(self, engine):
        resp = engine.load_world(Resource())
        assert resp.result.result == LoadWorldError.NO_RESOURCE

    def test_load_world_when_already_loaded(self, engine_with_world):
        resp = engine_with_world.load_world(Resource(uri="file:///worlds/other.sdf"))
        assert resp.result.result == ResultCode.INCORRECT_STATE

    def test_unload_world(self, engine_with_world):
        resp = engine_with_world.unload_world()
        assert resp.result.result == ResultCode.OK
        state = engine_with_world.get_simulation_state()
        assert state.state.state == SimStateCode.NO_WORLD

    def test_unload_world_when_no_world(self, engine):
        resp = engine.unload_world()
        assert resp.result.result == UnloadWorldError.NO_WORLD_LOADED

    def test_get_current_world(self, engine_with_world):
        resp = engine_with_world.get_current_world()
        assert resp.result.result == ResultCode.OK
        assert resp.world.world_resource.uri == "file:///worlds/test.sdf"

    def test_get_current_world_no_world(self, engine):
        resp = engine.get_current_world()
        assert resp.result.result == GetCurrentWorldError.NO_WORLD_LOADED

    def test_unload_from_playing(self, engine_playing):
        resp = engine_playing.unload_world()
        assert resp.result.result == ResultCode.OK
        state = engine_playing.get_simulation_state()
        assert state.state.state == SimStateCode.NO_WORLD

    def test_unload_clears_entities(self, engine_with_world):
        engine_with_world.spawn_entity("box", Resource(uri="model://box"))
        engine_with_world.unload_world()
        engine_with_world.load_world(Resource(uri="file:///worlds/test.sdf"))
        resp = engine_with_world.get_entities()
        assert len(resp.entities) == 0

    def test_unload_resets_simulation_time(self, engine_with_world):
        """Simulation time must be zero after unload and reload."""
        engine_with_world.set_simulation_state(
            SimulationState(SimStateCode.PLAYING))
        engine_with_world.set_simulation_state(
            SimulationState(SimStateCode.PAUSED))
        engine_with_world.step_simulation(500)
        engine_with_world.unload_world()
        engine_with_world.load_world(Resource(uri="file:///worlds/test2.sdf"))
        engine_with_world.set_simulation_state(
            SimulationState(SimStateCode.PLAYING))
        engine_with_world.set_simulation_state(
            SimulationState(SimStateCode.PAUSED))
        engine_with_world.spawn_entity("probe", Resource(uri="model://probe"))
        state = engine_with_world.get_entity_state("probe")
        assert state.state.header.stamp_sec == 0
        assert state.state.header.stamp_nanosec == 0


# ============================================================
# Test: State machine transitions
# ============================================================

class TestStateMachine:
    def test_stopped_to_playing(self, engine_with_world):
        resp = engine_with_world.set_simulation_state(SimulationState(SimStateCode.PLAYING))
        assert resp.result.result == ResultCode.OK
        state = engine_with_world.get_simulation_state()
        assert state.state.state == SimStateCode.PLAYING

    def test_playing_to_paused(self, engine_playing):
        resp = engine_playing.set_simulation_state(SimulationState(SimStateCode.PAUSED))
        assert resp.result.result == ResultCode.OK
        state = engine_playing.get_simulation_state()
        assert state.state.state == SimStateCode.PAUSED

    def test_paused_to_playing(self, engine_paused):
        resp = engine_paused.set_simulation_state(SimulationState(SimStateCode.PLAYING))
        assert resp.result.result == ResultCode.OK
        state = engine_paused.get_simulation_state()
        assert state.state.state == SimStateCode.PLAYING

    def test_playing_to_stopped(self, engine_playing):
        resp = engine_playing.set_simulation_state(SimulationState(SimStateCode.STOPPED))
        assert resp.result.result == ResultCode.OK
        state = engine_playing.get_simulation_state()
        assert state.state.state == SimStateCode.STOPPED

    def test_paused_to_stopped(self, engine_paused):
        resp = engine_paused.set_simulation_state(SimulationState(SimStateCode.STOPPED))
        assert resp.result.result == ResultCode.OK
        state = engine_paused.get_simulation_state()
        assert state.state.state == SimStateCode.STOPPED

    def test_stopped_to_paused_invalid(self, engine_with_world):
        resp = engine_with_world.set_simulation_state(SimulationState(SimStateCode.PAUSED))
        assert resp.result.result == SetSimStateError.INCORRECT_TRANSITION

    def test_already_in_target_state(self, engine_playing):
        resp = engine_playing.set_simulation_state(SimulationState(SimStateCode.PLAYING))
        assert resp.result.result == SetSimStateError.ALREADY_IN_TARGET_STATE

    def test_no_world_set_state(self, engine):
        resp = engine.set_simulation_state(SimulationState(SimStateCode.PLAYING))
        assert resp.result.result == ResultCode.INCORRECT_STATE

    def test_no_world_unsettable_target(self, engine):
        """QUITTING from NO_WORLD must return INCORRECT_STATE, not INCORRECT_TRANSITION."""
        resp = engine.set_simulation_state(SimulationState(SimStateCode.QUITTING))
        assert resp.result.result == ResultCode.INCORRECT_STATE

    def test_no_world_loading_target(self, engine):
        """LOADING_WORLD from NO_WORLD must return INCORRECT_STATE."""
        resp = engine.set_simulation_state(SimulationState(SimStateCode.LOADING_WORLD))
        assert resp.result.result == ResultCode.INCORRECT_STATE

    def test_invalid_target_quitting(self, engine_with_world):
        resp = engine_with_world.set_simulation_state(SimulationState(SimStateCode.QUITTING))
        assert resp.result.result == SetSimStateError.INCORRECT_TRANSITION

    def test_invalid_target_no_world(self, engine_with_world):
        resp = engine_with_world.set_simulation_state(SimulationState(SimStateCode.NO_WORLD))
        assert resp.result.result == SetSimStateError.INCORRECT_TRANSITION

    def test_invalid_target_loading(self, engine_with_world):
        resp = engine_with_world.set_simulation_state(SimulationState(SimStateCode.LOADING_WORLD))
        assert resp.result.result == SetSimStateError.INCORRECT_TRANSITION


# ============================================================
# Test: Entity spawning
# ============================================================

class TestSpawnEntity:
    def test_spawn_basic(self, engine_with_world):
        resp = engine_with_world.spawn_entity("robot1", Resource(uri="model://robot"))
        assert resp.result.result == ResultCode.OK
        assert resp.entity_name == "robot1"

    def test_spawn_empty_name(self, engine_with_world):
        resp = engine_with_world.spawn_entity("", Resource(uri="model://robot"))
        assert resp.result.result == SpawnErrorCode.NAME_INVALID

    def test_spawn_no_resource(self, engine_with_world):
        resp = engine_with_world.spawn_entity("robot1", Resource())
        assert resp.result.result == SpawnErrorCode.NO_RESOURCE

    def test_spawn_resource_string(self, engine_with_world):
        resp = engine_with_world.spawn_entity(
            "robot1", Resource(resource_string="<sdf><model name='x'/></sdf>"))
        assert resp.result.result == ResultCode.OK

    def test_spawn_duplicate_name_no_rename(self, engine_with_world):
        engine_with_world.spawn_entity("robot1", Resource(uri="model://robot"))
        resp = engine_with_world.spawn_entity("robot1", Resource(uri="model://robot"))
        assert resp.result.result == SpawnErrorCode.NAME_NOT_UNIQUE

    def test_spawn_duplicate_name_allow_rename(self, engine_with_world):
        engine_with_world.spawn_entity("robot", Resource(uri="model://robot"))
        resp = engine_with_world.spawn_entity(
            "robot", Resource(uri="model://robot"), allow_renaming=True)
        assert resp.result.result == ResultCode.OK
        assert resp.entity_name != "robot"
        assert resp.entity_name.startswith("robot_")

    def test_spawn_first_rename_suffix_is_zero(self, engine_with_world):
        """First auto-rename must append _0."""
        engine_with_world.spawn_entity("item", Resource(uri="model://item"))
        resp = engine_with_world.spawn_entity(
            "item", Resource(uri="model://item"), allow_renaming=True)
        assert resp.entity_name == "item_0"

    def test_spawn_multiple_renames(self, engine_with_world):
        engine_with_world.spawn_entity("box", Resource(uri="model://box"))
        r1 = engine_with_world.spawn_entity(
            "box", Resource(uri="model://box"), allow_renaming=True)
        r2 = engine_with_world.spawn_entity(
            "box", Resource(uri="model://box"), allow_renaming=True)
        assert r1.entity_name != r2.entity_name
        names = {"box", r1.entity_name, r2.entity_name}
        assert len(names) == 3

    def test_spawn_no_world(self, engine):
        resp = engine.spawn_entity("robot1", Resource(uri="model://robot"))
        assert resp.result.result == ResultCode.INCORRECT_STATE

    def test_spawn_with_pose(self, engine_with_world):
        pose = PoseStamped(pose=Pose(position=Vector3(1.0, 2.0, 3.0)))
        resp = engine_with_world.spawn_entity(
            "robot1", Resource(uri="model://robot"), initial_pose=pose)
        assert resp.result.result == ResultCode.OK
        state_resp = engine_with_world.get_entity_state("robot1")
        assert abs(state_resp.state.pose.position.x - 1.0) < 1e-6
        assert abs(state_resp.state.pose.position.y - 2.0) < 1e-6
        assert abs(state_resp.state.pose.position.z - 3.0) < 1e-6

    def test_spawn_while_playing(self, engine_playing):
        resp = engine_playing.spawn_entity("robot1", Resource(uri="model://robot"))
        assert resp.result.result == ResultCode.OK

    def test_spawn_while_paused(self, engine_paused):
        resp = engine_paused.spawn_entity("robot1", Resource(uri="model://robot"))
        assert resp.result.result == ResultCode.OK


# ============================================================
# Test: Batch spawning
# ============================================================

class TestSpawnEntities:
    def test_batch_spawn(self, engine_with_world):
        requests = [
            SpawnEntityMsg(name="box1", entity_resource=Resource(uri="model://box")),
            SpawnEntityMsg(name="box2", entity_resource=Resource(uri="model://box")),
            SpawnEntityMsg(name="box3", entity_resource=Resource(uri="model://box")),
        ]
        resp = engine_with_world.spawn_entities(requests)
        assert resp.result.result == ResultCode.OK
        assert len(resp.results) == 3
        for r in resp.results:
            assert r.result.result == ResultCode.OK

    def test_batch_spawn_partial_failure(self, engine_with_world):
        engine_with_world.spawn_entity("existing", Resource(uri="model://box"))
        requests = [
            SpawnEntityMsg(name="new1", entity_resource=Resource(uri="model://box")),
            SpawnEntityMsg(name="existing", entity_resource=Resource(uri="model://box")),
            SpawnEntityMsg(name="new2", entity_resource=Resource(uri="model://box")),
        ]
        resp = engine_with_world.spawn_entities(requests)
        assert resp.result.result == SpawnEntitiesError.ENTITIES_SPAWN_FAILED
        assert resp.results[0].result.result == ResultCode.OK
        assert resp.results[1].result.result == SpawnErrorCode.NAME_NOT_UNIQUE
        assert resp.results[2].result.result == ResultCode.OK

    def test_batch_spawn_no_world(self, engine):
        requests = [
            SpawnEntityMsg(name="box", entity_resource=Resource(uri="model://box"))]
        resp = engine.spawn_entities(requests)
        assert resp.result.result == ResultCode.INCORRECT_STATE

    def test_batch_intra_conflict(self, engine_with_world):
        """Second request conflicts with entity spawned by first request."""
        requests = [
            SpawnEntityMsg(name="dup", entity_resource=Resource(uri="model://box")),
            SpawnEntityMsg(name="dup", entity_resource=Resource(uri="model://box")),
        ]
        resp = engine_with_world.spawn_entities(requests)
        assert resp.result.result == SpawnEntitiesError.ENTITIES_SPAWN_FAILED
        assert resp.results[0].result.result == ResultCode.OK
        assert resp.results[1].result.result == SpawnErrorCode.NAME_NOT_UNIQUE


# ============================================================
# Test: Entity deletion
# ============================================================

class TestDeleteEntity:
    def test_delete_existing(self, engine_with_world):
        engine_with_world.spawn_entity("robot1", Resource(uri="model://robot"))
        resp = engine_with_world.delete_entity("robot1")
        assert resp.result.result == ResultCode.OK
        state_resp = engine_with_world.get_entity_state("robot1")
        assert state_resp.result.result == ResultCode.NOT_FOUND

    def test_delete_nonexistent(self, engine_with_world):
        resp = engine_with_world.delete_entity("ghost")
        assert resp.result.result == ResultCode.NOT_FOUND

    def test_delete_no_world(self, engine):
        resp = engine.delete_entity("robot1")
        assert resp.result.result == ResultCode.INCORRECT_STATE

    def test_respawn_after_delete(self, engine_with_world):
        """Deleted entity's name becomes available; respawned entity has fresh defaults."""
        pose = PoseStamped(pose=Pose(position=Vector3(5.0, 5.0, 5.0)))
        engine_with_world.spawn_entity(
            "bot", Resource(uri="model://bot"), initial_pose=pose)
        engine_with_world.set_entity_info("bot", EntityInfo(
            category=EntityCategory(CategoryCode.ROBOT), tags=["old"]))
        engine_with_world.delete_entity("bot")
        engine_with_world.spawn_entity("bot", Resource(uri="model://bot"))
        info = engine_with_world.get_entity_info("bot")
        assert info.info.category.category == CategoryCode.OBJECT
        assert info.info.tags == []
        state = engine_with_world.get_entity_state("bot")
        assert abs(state.state.pose.position.x) < 1e-6


# ============================================================
# Test: Entity state
# ============================================================

class TestEntityState:
    def test_get_state(self, engine_with_world):
        pose = PoseStamped(pose=Pose(position=Vector3(5.0, 6.0, 7.0)))
        engine_with_world.spawn_entity(
            "bot", Resource(uri="model://bot"), initial_pose=pose)
        resp = engine_with_world.get_entity_state("bot")
        assert resp.result.result == ResultCode.OK
        assert abs(resp.state.pose.position.x - 5.0) < 1e-6

    def test_get_state_nonexistent(self, engine_with_world):
        resp = engine_with_world.get_entity_state("ghost")
        assert resp.result.result == ResultCode.NOT_FOUND

    def test_set_state_pose_only(self, engine_with_world):
        engine_with_world.spawn_entity("bot", Resource(uri="model://bot"))
        new_state = EntityState(
            pose=Pose(position=Vector3(10.0, 20.0, 30.0)),
            twist=Twist(linear=Vector3(99.0, 99.0, 99.0)),
        )
        resp = engine_with_world.set_entity_state(
            "bot", new_state,
            set_pose=True, set_twist=False, set_acceleration=False)
        assert resp.result.result == ResultCode.OK
        got = engine_with_world.get_entity_state("bot")
        assert abs(got.state.pose.position.x - 10.0) < 1e-6
        # Twist should NOT have changed (was default 0,0,0)
        assert abs(got.state.twist.linear.x) < 1e-6

    def test_set_state_twist_only(self, engine_with_world):
        engine_with_world.spawn_entity(
            "bot", Resource(uri="model://bot"),
            initial_pose=PoseStamped(
                pose=Pose(position=Vector3(1.0, 2.0, 3.0))))
        new_state = EntityState(
            pose=Pose(position=Vector3(99.0, 99.0, 99.0)),
            twist=Twist(linear=Vector3(5.0, 6.0, 7.0)),
        )
        resp = engine_with_world.set_entity_state(
            "bot", new_state,
            set_pose=False, set_twist=True, set_acceleration=False)
        assert resp.result.result == ResultCode.OK
        got = engine_with_world.get_entity_state("bot")
        # Pose should NOT have changed
        assert abs(got.state.pose.position.x - 1.0) < 1e-6
        # Twist should have changed
        assert abs(got.state.twist.linear.x - 5.0) < 1e-6

    def test_set_state_nonexistent(self, engine_with_world):
        resp = engine_with_world.set_entity_state("ghost", EntityState())
        assert resp.result.result == ResultCode.NOT_FOUND

    def test_set_state_no_flags(self, engine_with_world):
        """All set_* flags false is a no-op that succeeds if entity exists."""
        engine_with_world.spawn_entity(
            "bot", Resource(uri="model://bot"),
            initial_pose=PoseStamped(
                pose=Pose(position=Vector3(1.0, 2.0, 3.0))))
        resp = engine_with_world.set_entity_state(
            "bot",
            EntityState(pose=Pose(position=Vector3(99.0, 99.0, 99.0))),
            set_pose=False, set_twist=False, set_acceleration=False)
        assert resp.result.result == ResultCode.OK
        got = engine_with_world.get_entity_state("bot")
        assert abs(got.state.pose.position.x - 1.0) < 1e-6

    def test_set_state_no_aliasing(self, engine_with_world):
        """Mutating the state object after set_entity_state must not affect entity."""
        engine_with_world.spawn_entity("bot", Resource(uri="model://bot"))
        new_state = EntityState(
            pose=Pose(position=Vector3(10.0, 20.0, 30.0)))
        engine_with_world.set_entity_state(
            "bot", new_state,
            set_pose=True, set_twist=False, set_acceleration=False)
        # Modify the original state object after the call
        new_state.pose.position.x = 999.0
        # Entity must NOT be affected
        got = engine_with_world.get_entity_state("bot")
        assert abs(got.state.pose.position.x - 10.0) < 1e-6


# ============================================================
# Test: Entity info
# ============================================================

class TestEntityInfo:
    def test_default_info(self, engine_with_world):
        engine_with_world.spawn_entity("bot", Resource(uri="model://bot"))
        resp = engine_with_world.get_entity_info("bot")
        assert resp.result.result == ResultCode.OK
        assert resp.info.category.category == CategoryCode.OBJECT
        assert resp.info.tags == []

    def test_set_info(self, engine_with_world):
        engine_with_world.spawn_entity("bot", Resource(uri="model://bot"))
        info = EntityInfo(
            category=EntityCategory(CategoryCode.ROBOT),
            description="A test robot",
            tags=["mobile", "autonomous"],
        )
        resp = engine_with_world.set_entity_info("bot", info)
        assert resp.result.result == ResultCode.OK
        got = engine_with_world.get_entity_info("bot")
        assert got.info.category.category == CategoryCode.ROBOT
        assert got.info.description == "A test robot"
        assert "mobile" in got.info.tags
        assert "autonomous" in got.info.tags

    def test_get_info_nonexistent(self, engine_with_world):
        resp = engine_with_world.get_entity_info("ghost")
        assert resp.result.result == ResultCode.NOT_FOUND

    def test_set_info_nonexistent(self, engine_with_world):
        resp = engine_with_world.set_entity_info("ghost", EntityInfo())
        assert resp.result.result == ResultCode.NOT_FOUND


# ============================================================
# Test: Entity filtering
# ============================================================

class TestEntityFiltering:
    @pytest.fixture
    def populated_engine(self, engine_with_world):
        """Engine with several entities for filtering tests."""
        e = engine_with_world

        e.spawn_entity("dingo_robot", Resource(uri="model://dingo"),
                       initial_pose=PoseStamped(
                           pose=Pose(position=Vector3(0.0, 0.0, 0.0))))
        e.set_entity_info("dingo_robot", EntityInfo(
            category=EntityCategory(CategoryCode.ROBOT),
            tags=["mobile", "ground"]))

        e.spawn_entity("ur10_arm", Resource(uri="model://ur10"),
                       initial_pose=PoseStamped(
                           pose=Pose(position=Vector3(5.0, 5.0, 0.0))))
        e.set_entity_info("ur10_arm", EntityInfo(
            category=EntityCategory(CategoryCode.ROBOT),
            tags=["manipulator", "fixed"]))

        e.spawn_entity("table", Resource(uri="model://table"),
                       initial_pose=PoseStamped(
                           pose=Pose(position=Vector3(5.0, 5.0, 0.0))))
        e.set_entity_info("table", EntityInfo(
            category=EntityCategory(CategoryCode.STATIC_OBJECT),
            tags=["furniture"]))

        e.spawn_entity("blue_cube_0", Resource(uri="model://cube"),
                       initial_pose=PoseStamped(
                           pose=Pose(position=Vector3(1.0, 1.0, 1.0))))
        e.set_entity_info("blue_cube_0", EntityInfo(
            category=EntityCategory(CategoryCode.DYNAMIC_OBJECT),
            tags=["cube", "blue", "small"]))

        e.spawn_entity("red_cube_0", Resource(uri="model://cube"),
                       initial_pose=PoseStamped(
                           pose=Pose(position=Vector3(2.0, 2.0, 1.0))))
        e.set_entity_info("red_cube_0", EntityInfo(
            category=EntityCategory(CategoryCode.DYNAMIC_OBJECT),
            tags=["cube", "red", "small"]))

        return e

    def test_no_filter(self, populated_engine):
        resp = populated_engine.get_entities()
        assert resp.result.result == ResultCode.OK
        assert len(resp.entities) == 5

    def test_name_filter(self, populated_engine):
        filters = EntityFilters(filter="cube")
        resp = populated_engine.get_entities(filters)
        assert set(resp.entities) == {"blue_cube_0", "red_cube_0"}

    def test_name_filter_robot(self, populated_engine):
        filters = EntityFilters(filter="robot")
        resp = populated_engine.get_entities(filters)
        assert resp.entities == ["dingo_robot"]

    def test_category_filter(self, populated_engine):
        filters = EntityFilters(
            categories=[EntityCategory(CategoryCode.ROBOT)])
        resp = populated_engine.get_entities(filters)
        assert set(resp.entities) == {"dingo_robot", "ur10_arm"}

    def test_category_filter_multiple(self, populated_engine):
        filters = EntityFilters(categories=[
            EntityCategory(CategoryCode.ROBOT),
            EntityCategory(CategoryCode.STATIC_OBJECT),
        ])
        resp = populated_engine.get_entities(filters)
        assert set(resp.entities) == {"dingo_robot", "ur10_arm", "table"}

    def test_tags_filter_any(self, populated_engine):
        filters = EntityFilters(tags=TagsFilter(
            tags=["mobile", "manipulator"],
            filter_mode=TagsFilter.FILTER_MODE_ANY))
        resp = populated_engine.get_entities(filters)
        assert set(resp.entities) == {"dingo_robot", "ur10_arm"}

    def test_tags_filter_all(self, populated_engine):
        filters = EntityFilters(tags=TagsFilter(
            tags=["cube", "blue"],
            filter_mode=TagsFilter.FILTER_MODE_ALL))
        resp = populated_engine.get_entities(filters)
        assert resp.entities == ["blue_cube_0"]

    def test_bounds_filter(self, populated_engine):
        filters = EntityFilters(bounds=Bounds(
            type=Bounds.TYPE_BOX,
            points=[Vector3(-0.5, -0.5, -0.5), Vector3(1.5, 1.5, 1.5)]))
        resp = populated_engine.get_entities(filters)
        assert set(resp.entities) == {"dingo_robot", "blue_cube_0"}

    def test_bounds_filter_boundary_inclusive(self, populated_engine):
        """Entity exactly on the max corner boundary must be included."""
        populated_engine.spawn_entity(
            "corner_ent", Resource(uri="model://m"),
            initial_pose=PoseStamped(
                pose=Pose(position=Vector3(2.0, 2.0, 1.0))))
        filters = EntityFilters(bounds=Bounds(
            type=Bounds.TYPE_BOX,
            points=[Vector3(0.0, 0.0, 0.0), Vector3(2.0, 2.0, 1.0)]))
        resp = populated_engine.get_entities(filters)
        assert "corner_ent" in resp.entities

    def test_combined_filters(self, populated_engine):
        filters = EntityFilters(
            categories=[EntityCategory(CategoryCode.DYNAMIC_OBJECT)],
            tags=TagsFilter(
                tags=["red"], filter_mode=TagsFilter.FILTER_MODE_ANY))
        resp = populated_engine.get_entities(filters)
        assert resp.entities == ["red_cube_0"]

    def test_empty_result(self, populated_engine):
        filters = EntityFilters(filter="nonexistent")
        resp = populated_engine.get_entities(filters)
        assert resp.entities == []


# ============================================================
# Test: Step simulation
# ============================================================

class TestStepSimulation:
    def test_step_when_paused(self, engine_paused):
        resp = engine_paused.step_simulation(10)
        assert resp.result.result == ResultCode.OK

    def test_step_when_playing(self, engine_playing):
        resp = engine_playing.step_simulation(1)
        assert resp.result.result == ResultCode.INCORRECT_STATE

    def test_step_when_stopped(self, engine_with_world):
        resp = engine_with_world.step_simulation(1)
        assert resp.result.result == ResultCode.INCORRECT_STATE

    def test_step_no_world(self, engine):
        resp = engine.step_simulation(1)
        assert resp.result.result == ResultCode.INCORRECT_STATE

    def test_step_advances_time(self, engine_paused):
        engine_paused.step_simulation(1000)  # 1000 steps * 1ms = 1 second
        engine_paused.spawn_entity("probe", Resource(uri="model://probe"))
        entity_state = engine_paused.get_entity_state("probe")
        assert entity_state.state.header.stamp_sec == 1
        assert entity_state.state.header.stamp_nanosec == 0

    def test_step_zero(self, engine_paused):
        resp = engine_paused.step_simulation(0)
        assert resp.result.result == ResultCode.OK

    def test_step_accumulates(self, engine_paused):
        engine_paused.step_simulation(500)   # 500ms
        engine_paused.step_simulation(700)   # +700ms = 1200ms = 1s 200ms
        engine_paused.spawn_entity("probe", Resource(uri="model://probe"))
        entity_state = engine_paused.get_entity_state("probe")
        assert entity_state.state.header.stamp_sec == 1
        assert entity_state.state.header.stamp_nanosec == 200_000_000

    def test_step_seconds_overflow(self, engine_paused):
        """Steps crossing multiple second boundaries decompose correctly."""
        engine_paused.step_simulation(2500)  # 2500ms = 2.5s
        engine_paused.spawn_entity("probe", Resource(uri="model://probe"))
        state = engine_paused.get_entity_state("probe")
        assert state.state.header.stamp_sec == 2
        assert state.state.header.stamp_nanosec == 500_000_000


# ============================================================
# Test: Reset simulation
# ============================================================

class TestResetSimulation:
    def test_reset_time(self, engine_paused):
        engine_paused.step_simulation(1000)
        resp = engine_paused.reset_simulation(ResetScope.TIME)
        assert resp.result.result == ResultCode.OK
        engine_paused.spawn_entity("probe", Resource(uri="model://probe"))
        entity_state = engine_paused.get_entity_state("probe")
        assert entity_state.state.header.stamp_sec == 0
        assert entity_state.state.header.stamp_nanosec == 0

    def test_reset_state(self, engine_paused):
        pose = PoseStamped(pose=Pose(position=Vector3(1.0, 2.0, 3.0)))
        engine_paused.spawn_entity(
            "bot", Resource(uri="model://bot"), initial_pose=pose)
        engine_paused.set_entity_state(
            "bot",
            EntityState(pose=Pose(position=Vector3(99.0, 99.0, 99.0))))
        engine_paused.reset_simulation(ResetScope.STATE)
        got = engine_paused.get_entity_state("bot")
        assert abs(got.state.pose.position.x - 1.0) < 1e-6
        assert abs(got.state.pose.position.y - 2.0) < 1e-6
        assert abs(got.state.pose.position.z - 3.0) < 1e-6

    def test_reset_spawned(self, engine_paused):
        engine_paused.spawn_entity("bot1", Resource(uri="model://bot"))
        engine_paused.spawn_entity("bot2", Resource(uri="model://bot"))
        engine_paused.reset_simulation(ResetScope.SPAWNED)
        resp = engine_paused.get_entities()
        assert len(resp.entities) == 0

    def test_reset_all(self, engine_paused):
        engine_paused.step_simulation(1000)
        engine_paused.spawn_entity("bot", Resource(uri="model://bot"))
        engine_paused.reset_simulation(ResetScope.ALL)
        resp = engine_paused.get_entities()
        assert len(resp.entities) == 0
        engine_paused.spawn_entity("probe", Resource(uri="model://probe"))
        entity_state = engine_paused.get_entity_state("probe")
        assert entity_state.state.header.stamp_sec == 0

    def test_reset_default_is_all(self, engine_paused):
        engine_paused.step_simulation(500)
        engine_paused.spawn_entity("bot", Resource(uri="model://bot"))
        engine_paused.reset_simulation(ResetScope.DEFAULT)
        resp = engine_paused.get_entities()
        assert len(resp.entities) == 0

    def test_reset_combined_scopes(self, engine_paused):
        pose = PoseStamped(pose=Pose(position=Vector3(1.0, 0.0, 0.0)))
        engine_paused.spawn_entity(
            "bot", Resource(uri="model://bot"), initial_pose=pose)
        engine_paused.set_entity_state(
            "bot",
            EntityState(pose=Pose(position=Vector3(50.0, 50.0, 50.0))))
        engine_paused.step_simulation(500)
        # Reset TIME | STATE (= 3)
        engine_paused.reset_simulation(ResetScope.TIME | ResetScope.STATE)
        # Entity should still exist but be reset to initial pose
        got = engine_paused.get_entity_state("bot")
        assert got.result.result == ResultCode.OK
        assert abs(got.state.pose.position.x - 1.0) < 1e-6
        # Time should be reset
        engine_paused.spawn_entity("probe", Resource(uri="model://probe"))
        probe_state = engine_paused.get_entity_state("probe")
        assert probe_state.state.header.stamp_sec == 0

    def test_reset_no_world(self, engine):
        resp = engine.reset_simulation(ResetScope.ALL)
        assert resp.result.result == ResultCode.INCORRECT_STATE

    def test_reset_preserves_sim_state(self, engine_paused):
        """Reset should not change the simulation state."""
        engine_paused.reset_simulation(ResetScope.ALL)
        state = engine_paused.get_simulation_state()
        assert state.state.state == SimStateCode.PAUSED

    def test_info_preserved_on_state_reset(self, engine_paused):
        """STATE reset restores dynamic state but preserves entity metadata."""
        engine_paused.spawn_entity("bot", Resource(uri="model://bot"))
        engine_paused.set_entity_info("bot", EntityInfo(
            category=EntityCategory(CategoryCode.ROBOT),
            description="Test robot",
            tags=["mobile"]))
        engine_paused.reset_simulation(ResetScope.STATE)
        info = engine_paused.get_entity_info("bot")
        assert info.info.category.category == CategoryCode.ROBOT
        assert info.info.description == "Test robot"
        assert "mobile" in info.info.tags

    def test_reset_spawned_and_state(self, engine_paused):
        """When SPAWNED and STATE are both active, entities are removed."""
        pose = PoseStamped(pose=Pose(position=Vector3(1.0, 2.0, 3.0)))
        engine_paused.spawn_entity(
            "bot", Resource(uri="model://bot"), initial_pose=pose)
        engine_paused.set_entity_state(
            "bot",
            EntityState(pose=Pose(position=Vector3(99.0, 99.0, 99.0))))
        engine_paused.reset_simulation(ResetScope.SPAWNED | ResetScope.STATE)
        resp = engine_paused.get_entities()
        assert len(resp.entities) == 0


# ============================================================
# Test: XML resource validation
# ============================================================

class TestXMLValidation:
    def test_spawn_invalid_xml(self, engine_with_world):
        """Plain text is not valid XML."""
        resp = engine_with_world.spawn_entity(
            "robot1", Resource(resource_string="this is not valid xml"))
        assert resp.result.result == SpawnErrorCode.RESOURCE_PARSE_ERROR

    def test_spawn_malformed_xml(self, engine_with_world):
        """Unclosed tags are not valid XML."""
        resp = engine_with_world.spawn_entity(
            "robot1", Resource(resource_string="<unclosed><tag>"))
        assert resp.result.result == SpawnErrorCode.RESOURCE_PARSE_ERROR

    def test_spawn_valid_sdf_xml(self, engine_with_world):
        """Well-formed SDF XML should succeed."""
        sdf = "<sdf version='1.7'><model name='test'><static>true</static></model></sdf>"
        resp = engine_with_world.spawn_entity(
            "robot1", Resource(resource_string=sdf))
        assert resp.result.result == ResultCode.OK

    def test_spawn_valid_urdf_xml(self, engine_with_world):
        """Well-formed URDF XML should succeed."""
        urdf = '<robot name="test"><link name="base_link"/></robot>'
        resp = engine_with_world.spawn_entity(
            "robot1", Resource(resource_string=urdf))
        assert resp.result.result == ResultCode.OK

    def test_xml_validation_before_uniqueness(self, engine_with_world):
        """Invalid resource_string on a duplicate name yields parse error."""
        engine_with_world.spawn_entity("dup", Resource(uri="model://box"))
        resp = engine_with_world.spawn_entity(
            "dup", Resource(resource_string="bad xml"))
        # Should get RESOURCE_PARSE_ERROR, not NAME_NOT_UNIQUE
        assert resp.result.result == SpawnErrorCode.RESOURCE_PARSE_ERROR

    def test_uri_resource_skips_xml_validation(self, engine_with_world):
        """URI-based resources are not validated as XML."""
        resp = engine_with_world.spawn_entity(
            "robot1", Resource(uri="model://robot"))
        assert resp.result.result == ResultCode.OK


# ============================================================
# Test: Warehouse simulation workflow (integration test)
# ============================================================

class TestWarehouseWorkflow:
    """Integration test mimicking the warehouse_simulation_script.py flow."""

    def test_full_workflow(self, engine):
        # 1. Check features
        features = engine.get_simulator_features()
        assert FeatureCode.SPAWNING in features.features.features

        # 2. Load world
        resp = engine.load_world(Resource(uri="file:///worlds/warehouse.sdf"))
        assert resp.result.result == ResultCode.OK

        # 3. Spawn and despawn a table (test spawn/delete cycle)
        r = engine.spawn_entity("table_test", Resource(uri="model://table"))
        assert r.result.result == ResultCode.OK
        r = engine.delete_entity("table_test")
        assert r.result.result == ResultCode.OK

        # 4. Spawn full scene
        scene_entities = [
            ("table", Resource(uri="model://table"), Vector3(-1.0, -1.5, 1.19)),
            ("dingo", Resource(uri="model://dingo"), Vector3(-4.0, -3.0, 0.0)),
            ("ur10", Resource(uri="model://ur10"), Vector3(-1.0, -2.14, 1.19)),
        ]
        for name, res, pos in scene_entities:
            r = engine.spawn_entity(
                name, res,
                initial_pose=PoseStamped(pose=Pose(position=pos)))
            assert r.result.result == ResultCode.OK

        # Spawn 7 cubes
        for i in range(7):
            color = "blue" if i % 2 == 0 else "red"
            r = engine.spawn_entity(
                f"{color}_cube_{i}",
                Resource(uri=f"model://{color}_cube"),
                initial_pose=PoseStamped(
                    pose=Pose(position=Vector3(0.0, 0.0, 1.34))))
            assert r.result.result == ResultCode.OK

        # 5. Play simulation
        r = engine.set_simulation_state(
            SimulationState(SimStateCode.PLAYING))
        assert r.result.result == ResultCode.OK

        # 6. Pause simulation
        r = engine.set_simulation_state(
            SimulationState(SimStateCode.PAUSED))
        assert r.result.result == ResultCode.OK

        # 7. Move cubes
        for i in range(7):
            color = "blue" if i % 2 == 0 else "red"
            name = f"{color}_cube_{i}"
            new_state = EntityState(
                pose=Pose(position=Vector3(float(i), float(i), 1.34)))
            r = engine.set_entity_state(
                name, new_state,
                set_pose=True, set_twist=False, set_acceleration=False)
            assert r.result.result == ResultCode.OK

        # 8. Step simulation 15 iterations of 2 steps
        for _ in range(15):
            r = engine.step_simulation(2)
            assert r.result.result == ResultCode.OK

        # 9. Spawn obstacles
        for j in range(3):
            r = engine.spawn_entity(
                f"cardboard_{j}",
                Resource(uri="model://cardboard"),
                initial_pose=PoseStamped(
                    pose=Pose(
                        position=Vector3(-2.5 + j, -2.5 + j, 0.0))))
            assert r.result.result == ResultCode.OK

        # 10. Verify entity count
        resp = engine.get_entities()
        assert len(resp.entities) == 13  # 3 scene + 7 cubes + 3 cardboard

        # 11. Reset STATE scope — entities remain at initial pose
        r = engine.reset_simulation(ResetScope.STATE)
        assert r.result.result == ResultCode.OK

        # Verify dingo is back at initial position
        dingo_state = engine.get_entity_state("dingo")
        assert abs(dingo_state.state.pose.position.x - (-4.0)) < 1e-6

        # 12. Unload world
        r = engine.unload_world()
        assert r.result.result == ResultCode.OK
        state = engine.get_simulation_state()
        assert state.state.state == SimStateCode.NO_WORLD
