
import json
import os
import re

import pytest

STATE_PATH = "/app/refactored.tfstate"
MOVED_PATH = "/app/moved.tf"
ORIGINAL_STATE_PATH = "/app/monolith.tfstate"


@pytest.fixture(scope="module")
def original_state():
    with open(ORIGINAL_STATE_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def refactored_state():
    assert os.path.exists(STATE_PATH), f"Output state file not found at {STATE_PATH}"
    with open(STATE_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def moved_content():
    assert os.path.exists(MOVED_PATH), f"Moved blocks file not found at {MOVED_PATH}"
    with open(MOVED_PATH) as f:
        return f.read()


# ---------- State file structural validity ----------

class TestStateStructure:
    def test_version_is_4(self, refactored_state):
        assert refactored_state["version"] == 4

    def test_terraform_version_preserved(self, refactored_state, original_state):
        assert refactored_state["terraform_version"] == original_state["terraform_version"]

    def test_lineage_preserved(self, refactored_state, original_state):
        assert refactored_state["lineage"] == original_state["lineage"]

    def test_serial_incremented(self, refactored_state, original_state):
        assert refactored_state["serial"] > original_state["serial"]

    def test_has_resources(self, refactored_state):
        assert "resources" in refactored_state
        assert len(refactored_state["resources"]) > 0

    def test_all_resources_have_required_fields(self, refactored_state):
        for res in refactored_state["resources"]:
            assert "mode" in res, f"Resource missing 'mode': {res.get('type')}.{res.get('name')}"
            assert "type" in res, f"Resource missing 'type'"
            assert "name" in res, f"Resource missing 'name'"
            assert "provider" in res, f"Resource missing 'provider': {res['type']}.{res['name']}"
            assert "instances" in res, f"Resource missing 'instances': {res['type']}.{res['name']}"


# ---------- Resource count and completeness ----------

class TestCompleteness:
    def _count_instances(self, state):
        total = 0
        for res in state["resources"]:
            total += len(res["instances"])
        return total

    def test_total_instance_count_preserved(self, refactored_state, original_state):
        """All 20 instances (19 active + 1 deposed) from input must appear in output."""
        orig_count = self._count_instances(original_state)
        new_count = self._count_instances(refactored_state)
        assert new_count == orig_count, f"Instance count mismatch: {new_count} != {orig_count}"

    def test_expected_resource_count(self, refactored_state):
        """Should have exactly 13 resource entries after transformation."""
        assert len(refactored_state["resources"]) == 13

    def test_no_duplicate_instance_ids(self, refactored_state):
        """No two active instances should share the same resource ID."""
        seen_ids = set()
        for res in refactored_state["resources"]:
            for inst in res["instances"]:
                if "deposed" in inst:
                    continue  # deposed instances may share IDs with replacements
                rid = inst["attributes"]["id"]
                assert rid not in seen_ids, f"Duplicate instance id: {rid}"
                seen_ids.add(rid)


# ---------- Helper to find resources ----------

def find_resource(state, module, rtype, rname):
    for res in state["resources"]:
        res_module = res.get("module", "")
        if res_module == module and res["type"] == rtype and res["name"] == rname:
            return res
    return None


def find_instance(resource, index_key=None):
    if resource is None:
        return None
    for inst in resource["instances"]:
        if "deposed" in inst:
            continue
        inst_key = inst.get("index_key")
        if inst_key == index_key:
            return inst
    return None


# ---------- Simple module move ----------

class TestSimpleModuleMove:
    def test_vpc_moved_to_networking_module(self, refactored_state):
        res = find_resource(refactored_state, "module.networking", "aws_vpc", "this")
        assert res is not None, "aws_vpc.this not found in module.networking"

    def test_vpc_attributes_preserved(self, refactored_state):
        res = find_resource(refactored_state, "module.networking", "aws_vpc", "this")
        inst = find_instance(res)
        assert inst is not None
        assert inst["attributes"]["id"] == "vpc-0a1b2c3d4e5f67890"
        assert inst["attributes"]["cidr_block"] == "10.0.0.0/16"
        assert inst["attributes"]["enable_dns_hostnames"] is True

    def test_vpc_no_index_key(self, refactored_state):
        res = find_resource(refactored_state, "module.networking", "aws_vpc", "this")
        inst = find_instance(res)
        assert inst is not None
        assert "index_key" not in inst or inst.get("index_key") is None

    def test_vpc_provider_preserved(self, refactored_state):
        res = find_resource(refactored_state, "module.networking", "aws_vpc", "this")
        assert 'registry.terraform.io/hashicorp/aws' in res["provider"]


# ---------- Count to for_each conversion ----------

class TestCountToForEach:
    def test_public_subnets_exist_in_networking(self, refactored_state):
        res = find_resource(refactored_state, "module.networking", "aws_subnet", "public")
        assert res is not None, "aws_subnet.public not found in module.networking"

    def test_public_subnets_have_three_instances(self, refactored_state):
        res = find_resource(refactored_state, "module.networking", "aws_subnet", "public")
        assert len(res["instances"]) == 3

    def test_public_subnet_keys_are_strings(self, refactored_state):
        res = find_resource(refactored_state, "module.networking", "aws_subnet", "public")
        keys = {inst["index_key"] for inst in res["instances"]}
        assert keys == {"us-east-1a", "us-east-1b", "us-east-1c"}

    def test_public_subnet_attributes_mapped_correctly(self, refactored_state):
        res = find_resource(refactored_state, "module.networking", "aws_subnet", "public")
        inst_a = find_instance(res, "us-east-1a")
        assert inst_a is not None
        assert inst_a["attributes"]["id"] == "subnet-pub-0aaa111"
        assert inst_a["attributes"]["availability_zone"] == "us-east-1a"
        assert inst_a["attributes"]["cidr_block"] == "10.0.1.0/24"

    def test_public_subnet_b_attributes(self, refactored_state):
        res = find_resource(refactored_state, "module.networking", "aws_subnet", "public")
        inst_b = find_instance(res, "us-east-1b")
        assert inst_b is not None
        assert inst_b["attributes"]["id"] == "subnet-pub-0bbb222"

    def test_public_subnet_c_attributes(self, refactored_state):
        res = find_resource(refactored_state, "module.networking", "aws_subnet", "public")
        inst_c = find_instance(res, "us-east-1c")
        assert inst_c is not None
        assert inst_c["attributes"]["id"] == "subnet-pub-0ccc333"


# ---------- Rename + module move ----------

class TestRenameAndModuleMove:
    def test_web_sg_renamed_to_web(self, refactored_state):
        res = find_resource(refactored_state, "module.networking", "aws_security_group", "web")
        assert res is not None
        inst = find_instance(res)
        assert inst["attributes"]["id"] == "sg-0web111aaa"

    def test_db_sg_renamed_to_database(self, refactored_state):
        res = find_resource(refactored_state, "module.networking", "aws_security_group", "database")
        assert res is not None
        inst = find_instance(res)
        assert inst["attributes"]["id"] == "sg-0db222bbb"

    def test_db_replica_renamed(self, refactored_state):
        res = find_resource(refactored_state, "module.database", "aws_db_instance", "read_replica")
        assert res is not None
        inst = find_instance(res)
        assert inst["attributes"]["id"] == "mydb-replica"
        assert inst["attributes"]["engine"] == "postgres"

    def test_iam_role_renamed(self, refactored_state):
        res = find_resource(refactored_state, "module.compute", "aws_iam_role", "instance_role")
        assert res is not None
        inst = find_instance(res)
        assert inst["attributes"]["id"] == "ec2-instance-role"


# ---------- Nested module + rename + count->for_each ----------

class TestNestedModuleTransformation:
    def test_web_instances_in_nested_module(self, refactored_state):
        res = find_resource(
            refactored_state,
            "module.compute.module.web_servers",
            "aws_instance",
            "this"
        )
        assert res is not None, "aws_instance.this not found in module.compute.module.web_servers"

    def test_web_instances_have_correct_keys(self, refactored_state):
        res = find_resource(
            refactored_state,
            "module.compute.module.web_servers",
            "aws_instance",
            "this"
        )
        active_keys = {
            inst["index_key"] for inst in res["instances"]
            if "deposed" not in inst
        }
        assert active_keys == {"primary", "secondary"}

    def test_web_primary_attributes(self, refactored_state):
        res = find_resource(
            refactored_state,
            "module.compute.module.web_servers",
            "aws_instance",
            "this"
        )
        inst = find_instance(res, "primary")
        assert inst is not None
        assert inst["attributes"]["id"] == "i-web001abc"
        assert inst["attributes"]["instance_type"] == "t3.medium"
        assert inst["attributes"]["private_ip"] == "10.0.1.10"

    def test_web_secondary_attributes(self, refactored_state):
        res = find_resource(
            refactored_state,
            "module.compute.module.web_servers",
            "aws_instance",
            "this"
        )
        inst = find_instance(res, "secondary")
        assert inst is not None
        assert inst["attributes"]["id"] == "i-web002def"

    def test_worker_instances_in_nested_module(self, refactored_state):
        res = find_resource(
            refactored_state,
            "module.compute.module.workers",
            "aws_instance",
            "this"
        )
        assert res is not None

    def test_worker_instances_have_correct_keys(self, refactored_state):
        res = find_resource(
            refactored_state,
            "module.compute.module.workers",
            "aws_instance",
            "this"
        )
        keys = {inst["index_key"] for inst in res["instances"]}
        assert keys == {"w1", "w2", "w3"}

    def test_worker_w1_attributes(self, refactored_state):
        res = find_resource(
            refactored_state,
            "module.compute.module.workers",
            "aws_instance",
            "this"
        )
        inst = find_instance(res, "w1")
        assert inst["attributes"]["id"] == "i-wrk001ghi"

    def test_worker_w3_attributes(self, refactored_state):
        res = find_resource(
            refactored_state,
            "module.compute.module.workers",
            "aws_instance",
            "this"
        )
        inst = find_instance(res, "w3")
        assert inst["attributes"]["id"] == "i-wrk003mno"


# ---------- Simple module-only moves ----------

class TestModuleOnlyMoves:
    def test_db_primary_in_database_module(self, refactored_state):
        res = find_resource(refactored_state, "module.database", "aws_db_instance", "primary")
        assert res is not None
        inst = find_instance(res)
        assert inst["attributes"]["id"] == "mydb-primary"
        assert inst["attributes"]["engine"] == "postgres"
        assert inst["attributes"]["instance_class"] == "db.r6g.large"

    def test_s3_logs_in_storage_module(self, refactored_state):
        res = find_resource(refactored_state, "module.storage", "aws_s3_bucket", "logs")
        assert res is not None
        inst = find_instance(res)
        assert inst["attributes"]["id"] == "my-logs-bucket-12345"

    def test_s3_assets_in_storage_module(self, refactored_state):
        res = find_resource(refactored_state, "module.storage", "aws_s3_bucket", "assets")
        assert res is not None
        inst = find_instance(res)
        assert inst["attributes"]["id"] == "my-assets-bucket-67890"


# ---------- S3 replica in nested storage module ----------

class TestS3ReplicaPlacement:
    def test_replica_in_nested_storage_module(self, refactored_state):
        res = find_resource(
            refactored_state,
            "module.storage.module.replication",
            "aws_s3_bucket",
            "target"
        )
        assert res is not None, "aws_s3_bucket.target not found in module.storage.module.replication"

    def test_replica_attributes(self, refactored_state):
        res = find_resource(
            refactored_state,
            "module.storage.module.replication",
            "aws_s3_bucket",
            "target"
        )
        inst = find_instance(res)
        assert inst["attributes"]["id"] == "my-replica-bucket-99999"
        assert inst["attributes"]["region"] == "us-west-2"

    def test_replica_no_index_key(self, refactored_state):
        res = find_resource(
            refactored_state,
            "module.storage.module.replication",
            "aws_s3_bucket",
            "target"
        )
        inst = find_instance(res)
        assert "index_key" not in inst or inst.get("index_key") is None


# ---------- NAT gateway count->for_each + rename ----------

class TestNatGatewayTransformation:
    def test_nat_gateways_renamed_and_moved(self, refactored_state):
        res = find_resource(refactored_state, "module.networking", "aws_nat_gateway", "az")
        assert res is not None

    def test_nat_gateways_have_string_keys(self, refactored_state):
        res = find_resource(refactored_state, "module.networking", "aws_nat_gateway", "az")
        keys = {inst["index_key"] for inst in res["instances"]}
        assert keys == {"us-east-1a", "us-east-1b"}

    def test_nat_gateway_a_attributes(self, refactored_state):
        res = find_resource(refactored_state, "module.networking", "aws_nat_gateway", "az")
        inst = find_instance(res, "us-east-1a")
        assert inst["attributes"]["id"] == "nat-0aaa111xyz"
        assert inst["attributes"]["public_ip"] == "3.210.11.22"

    def test_nat_gateway_b_attributes(self, refactored_state):
        res = find_resource(refactored_state, "module.networking", "aws_nat_gateway", "az")
        inst = find_instance(res, "us-east-1b")
        assert inst["attributes"]["id"] == "nat-0bbb222uvw"


# ---------- Provider alias preservation ----------

class TestProviderAliasPreservation:
    def test_s3_replica_uses_aliased_provider(self, refactored_state):
        """Cross-region S3 bucket must retain its provider alias."""
        res = find_resource(
            refactored_state,
            "module.storage.module.replication",
            "aws_s3_bucket",
            "target"
        )
        assert res is not None
        assert ".us_west_2" in res["provider"], (
            f"Provider alias lost: expected '.us_west_2' in '{res['provider']}'"
        )

    def test_default_provider_resources_unchanged(self, refactored_state):
        """Resources using the default provider should not have an alias suffix."""
        res = find_resource(refactored_state, "module.networking", "aws_vpc", "this")
        # Should end with "]" and not have a dot-suffix after closing bracket
        assert res["provider"].endswith('"]')

    def test_all_provider_strings_well_formed(self, refactored_state):
        """Every provider string must contain the registry path."""
        for res in refactored_state["resources"]:
            assert "registry.terraform.io" in res["provider"], (
                f"Malformed provider for {res.get('module', '')}.{res['type']}.{res['name']}: "
                f"{res['provider']}"
            )


# ---------- Tainted status preservation ----------

class TestTaintedStatusPreservation:
    def test_tainted_worker_count(self, refactored_state):
        """Exactly one worker instance should be marked as tainted."""
        res = find_resource(
            refactored_state,
            "module.compute.module.workers",
            "aws_instance",
            "this"
        )
        tainted = [inst for inst in res["instances"] if inst.get("status") == "tainted"]
        assert len(tainted) == 1, f"Expected 1 tainted instance, found {len(tainted)}"

    def test_tainted_worker_is_w2(self, refactored_state):
        """The w2 worker (originally worker[1]) should be tainted."""
        res = find_resource(
            refactored_state,
            "module.compute.module.workers",
            "aws_instance",
            "this"
        )
        w2 = find_instance(res, "w2")
        assert w2 is not None
        assert w2.get("status") == "tainted", (
            f"Worker w2 should be tainted but status is: {w2.get('status')}"
        )

    def test_non_tainted_workers(self, refactored_state):
        """Workers w1 and w3 should not have a tainted status."""
        res = find_resource(
            refactored_state,
            "module.compute.module.workers",
            "aws_instance",
            "this"
        )
        for key in ["w1", "w3"]:
            inst = find_instance(res, key)
            assert inst.get("status") is None or "status" not in inst, (
                f"Worker {key} should not be tainted"
            )


# ---------- Deposed instance preservation ----------

class TestDeposedInstancePreservation:
    def test_deposed_instance_present_in_web_servers(self, refactored_state):
        """The deposed instance from aws_instance.web must be carried to the target."""
        res = find_resource(
            refactored_state,
            "module.compute.module.web_servers",
            "aws_instance",
            "this"
        )
        deposed = [inst for inst in res["instances"] if "deposed" in inst]
        assert len(deposed) == 1, f"Expected 1 deposed instance, found {len(deposed)}"

    def test_deposed_instance_key(self, refactored_state):
        """The deposed instance should preserve its deposed key."""
        res = find_resource(
            refactored_state,
            "module.compute.module.web_servers",
            "aws_instance",
            "this"
        )
        deposed = [inst for inst in res["instances"] if "deposed" in inst][0]
        assert deposed["deposed"] == "00000001"

    def test_deposed_instance_attributes(self, refactored_state):
        """The deposed instance's attributes must be preserved."""
        res = find_resource(
            refactored_state,
            "module.compute.module.web_servers",
            "aws_instance",
            "this"
        )
        deposed = [inst for inst in res["instances"] if "deposed" in inst][0]
        assert deposed["attributes"]["id"] == "i-web000old"
        assert deposed["attributes"]["instance_type"] == "t3.small"

    def test_web_servers_total_instance_count(self, refactored_state):
        """Web servers resource should have 3 instances: 2 active + 1 deposed."""
        res = find_resource(
            refactored_state,
            "module.compute.module.web_servers",
            "aws_instance",
            "this"
        )
        assert len(res["instances"]) == 3


# ---------- depends_on remapping ----------

class TestDependsOnRemapping:
    def test_web_instances_have_depends_on(self, refactored_state):
        """Web instances had depends_on in source — it must be present in output."""
        res = find_resource(
            refactored_state,
            "module.compute.module.web_servers",
            "aws_instance",
            "this"
        )
        assert "depends_on" in res, "depends_on missing from web instances resource"

    def test_web_depends_on_uses_new_addresses(self, refactored_state):
        """depends_on must reference the new module addresses, not the old root ones."""
        res = find_resource(
            refactored_state,
            "module.compute.module.web_servers",
            "aws_instance",
            "this"
        )
        deps = res["depends_on"]
        for dep in deps:
            assert dep.startswith("module."), (
                f"depends_on contains unrelocated address: {dep}"
            )

    def test_web_depends_on_correct_targets(self, refactored_state):
        res = find_resource(
            refactored_state,
            "module.compute.module.web_servers",
            "aws_instance",
            "this"
        )
        deps = set(res["depends_on"])
        assert "module.networking.aws_security_group.web" in deps, (
            f"Missing security group dependency: {deps}"
        )
        assert "module.networking.aws_subnet.public" in deps, (
            f"Missing subnet dependency: {deps}"
        )

    def test_nat_gateway_depends_on_remapped(self, refactored_state):
        res = find_resource(refactored_state, "module.networking", "aws_nat_gateway", "az")
        assert "depends_on" in res, "depends_on missing from NAT gateway resource"
        assert "module.networking.aws_subnet.public" in res["depends_on"]

    def test_db_replica_depends_on_remapped(self, refactored_state):
        res = find_resource(refactored_state, "module.database", "aws_db_instance", "read_replica")
        assert "depends_on" in res, "depends_on missing from DB replica resource"
        assert "module.database.aws_db_instance.primary" in res["depends_on"]

    def test_no_stale_depends_on_references(self, refactored_state):
        """No resource should have depends_on referencing old root-level addresses."""
        for res in refactored_state["resources"]:
            if "depends_on" in res:
                for dep in res["depends_on"]:
                    assert "module." in dep, (
                        f"Stale depends_on in "
                        f"{res.get('module', '')}.{res['type']}.{res['name']}: {dep}"
                    )


# ---------- Sensitive attributes and private data preserved ----------

class TestMetadataPreservation:
    def test_sensitive_attributes_preserved(self, refactored_state):
        """DB primary has sensitive_attributes for password — must be preserved."""
        res = find_resource(refactored_state, "module.database", "aws_db_instance", "primary")
        inst = find_instance(res)
        assert len(inst["sensitive_attributes"]) > 0

    def test_private_field_preserved(self, refactored_state):
        """Private (provider-internal) data must be preserved."""
        res = find_resource(refactored_state, "module.database", "aws_db_instance", "primary")
        inst = find_instance(res)
        assert "private" in inst
        assert len(inst["private"]) > 0

    def test_schema_version_preserved(self, refactored_state):
        """Schema versions differ per resource type — must be preserved."""
        res = find_resource(refactored_state, "module.database", "aws_db_instance", "primary")
        inst = find_instance(res)
        assert inst["schema_version"] == 2

    def test_s3_schema_version(self, refactored_state):
        res = find_resource(refactored_state, "module.storage", "aws_s3_bucket", "logs")
        inst = find_instance(res)
        assert inst["schema_version"] == 0


# ---------- No root-level resources remain ----------

class TestNoRootResources:
    def test_no_resources_at_root_module(self, refactored_state):
        """All resources should have been moved into modules."""
        for res in refactored_state["resources"]:
            module = res.get("module", "")
            assert module != "", (
                f"Resource {res['type']}.{res['name']} still at root module"
            )


# ---------- Moved blocks ----------

class TestMovedBlocks:
    def test_moved_file_exists(self, moved_content):
        assert len(moved_content) > 0

    def test_correct_number_of_moved_blocks(self, moved_content):
        count = moved_content.count("moved {")
        assert count == 19, f"Expected 19 moved blocks, found {count}"

    def test_vpc_moved_block(self, moved_content):
        assert "aws_vpc.main" in moved_content
        assert "module.networking.aws_vpc.this" in moved_content

    def test_subnet_moved_block_with_for_each_key(self, moved_content):
        assert 'module.networking.aws_subnet.public["us-east-1a"]' in moved_content
        assert 'module.networking.aws_subnet.public["us-east-1b"]' in moved_content
        assert 'module.networking.aws_subnet.public["us-east-1c"]' in moved_content

    def test_nested_module_moved_block(self, moved_content):
        assert 'module.compute.module.web_servers.aws_instance.this["primary"]' in moved_content
        assert 'module.compute.module.web_servers.aws_instance.this["secondary"]' in moved_content

    def test_worker_moved_blocks(self, moved_content):
        assert 'module.compute.module.workers.aws_instance.this["w1"]' in moved_content
        assert 'module.compute.module.workers.aws_instance.this["w2"]' in moved_content
        assert 'module.compute.module.workers.aws_instance.this["w3"]' in moved_content

    def test_db_replica_moved_block(self, moved_content):
        assert "aws_db_instance.replica" in moved_content
        assert "module.database.aws_db_instance.read_replica" in moved_content

    def test_iam_role_moved_block(self, moved_content):
        assert "aws_iam_role.ec2_role" in moved_content
        assert "module.compute.aws_iam_role.instance_role" in moved_content

    def test_nat_gateway_moved_blocks(self, moved_content):
        assert 'module.networking.aws_nat_gateway.az["us-east-1a"]' in moved_content
        assert 'module.networking.aws_nat_gateway.az["us-east-1b"]' in moved_content

    def test_s3_replica_moved_block(self, moved_content):
        assert "aws_s3_bucket.replica" in moved_content
        assert "module.storage.module.replication.aws_s3_bucket.target" in moved_content

    def test_moved_blocks_have_from_and_to(self, moved_content):
        """Each moved block must have both from and to."""
        blocks = re.findall(r'moved\s*\{[^}]+\}', moved_content)
        assert len(blocks) == 19
        for block in blocks:
            assert "from" in block, f"Block missing 'from': {block}"
            assert "to" in block, f"Block missing 'to': {block}"

    def test_count_index_in_from_address(self, moved_content):
        """Source addresses with count should use integer bracket syntax."""
        assert "aws_subnet.public[0]" in moved_content
        assert "aws_subnet.public[1]" in moved_content
        assert "aws_subnet.public[2]" in moved_content
        assert "aws_instance.web[0]" in moved_content
        assert "aws_instance.web[1]" in moved_content
        assert "aws_instance.worker[0]" in moved_content
        assert "aws_nat_gateway.main[0]" in moved_content


# ---------- Full attribute fidelity ----------

class TestAttributeFidelity:
    def test_complex_attribute_preserved(self, refactored_state):
        """Security group ingress rules (list of objects) must be preserved exactly."""
        res = find_resource(refactored_state, "module.networking", "aws_security_group", "web")
        inst = find_instance(res)
        ingress = inst["attributes"]["ingress"]
        assert len(ingress) == 2
        ports = {rule["from_port"] for rule in ingress}
        assert ports == {80, 443}

    def test_tags_preserved(self, refactored_state):
        """Tags maps must be preserved."""
        res = find_resource(refactored_state, "module.networking", "aws_vpc", "this")
        inst = find_instance(res)
        assert inst["attributes"]["tags"]["Environment"] == "production"
        assert inst["attributes"]["tags"]["Name"] == "main-vpc"

    def test_iam_assume_role_policy_preserved(self, refactored_state):
        """JSON string attributes must be preserved verbatim."""
        res = find_resource(refactored_state, "module.compute", "aws_iam_role", "instance_role")
        inst = find_instance(res)
        policy = json.loads(inst["attributes"]["assume_role_policy"])
        assert policy["Version"] == "2012-10-17"
        assert policy["Statement"][0]["Principal"]["Service"] == "ec2.amazonaws.com"
