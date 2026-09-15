
import json
import os
import pytest
from jsonschema import validate, ValidationError

OUTPUT_DIR = "/app/output"
BACKUP_OUTPUT = os.path.join(OUTPUT_DIR, "backup_descriptor.json")
REPORT_OUTPUT = os.path.join(OUTPUT_DIR, "migration_report.json")


@pytest.fixture
def output_backup():
    with open(BACKUP_OUTPUT) as f:
        return json.load(f)


@pytest.fixture
def migration_report():
    with open(REPORT_OUTPUT) as f:
        return json.load(f)


@pytest.fixture
def target_config():
    with open("/app/target_config.json") as f:
        raw = json.load(f)
    config = dict(raw)
    if "resources" in config:
        config["max_vector_cache_objects"] = config["resources"]["max_vector_cache_objects"]
        config["memory_per_node_mb"] = config["resources"]["memory_per_node_mb"]
        config["hnsw_memory_budget_bytes_per_node"] = config["resources"].get(
            "hnsw_memory_budget_bytes_per_node"
        )
    if "installed_modules" in config:
        config["available_modules"] = config["installed_modules"]
    if "tokenizer_support" in config:
        config["supported_tokenizers"] = set(config["tokenizer_support"])
    return config


@pytest.fixture
def source_backup():
    with open("/app/backup/backup_descriptor.json") as f:
        return json.load(f)


def _get_collection(output_backup, name):
    matches = [c for c in output_backup["collections"] if c["class"] == name]
    assert len(matches) == 1, f"Expected exactly 1 collection named {name}, found {len(matches)}"
    return matches[0]


# ---- Schema validation tests ----

def test_backup_descriptor_conforms_to_schema(output_backup):
    with open("/app/schemas/backup_descriptor_schema.json") as f:
        schema = json.load(f)
    try:
        validate(instance=output_backup, schema=schema)
    except ValidationError as e:
        pytest.fail(f"Output backup descriptor does not conform to schema: {e.message}")


def test_migration_report_conforms_to_schema(migration_report):
    with open("/app/schemas/migration_report_schema.json") as f:
        schema = json.load(f)
    try:
        validate(instance=migration_report, schema=schema)
    except ValidationError as e:
        pytest.fail(f"Migration report does not conform to schema: {e.message}")


# ---- Structural tests ----

def test_output_files_exist():
    assert os.path.exists(BACKUP_OUTPUT), "Output backup descriptor must exist at /app/output/backup_descriptor.json"
    assert os.path.exists(REPORT_OUTPUT), "Migration report must exist at /app/output/migration_report.json"


def test_output_valid_json_structure(output_backup):
    assert "id" in output_backup
    assert "server_version" in output_backup
    assert "cluster" in output_backup
    assert "collections" in output_backup
    assert isinstance(output_backup["collections"], list)


def test_four_collections_in_output(output_backup):
    assert len(output_backup["collections"]) == 4, (
        f"Expected 4 collections, got {len(output_backup['collections'])}"
    )


def test_server_version_updated(output_backup, target_config):
    assert output_backup["server_version"] == target_config["version"], (
        f"server_version should be {target_config['version']}, got {output_backup['server_version']}"
    )


def test_only_target_nodes_in_cluster(output_backup, target_config):
    target_node_names = {n["name"] for n in target_config["nodes"]}
    cluster_nodes = set(output_backup["cluster"]["nodes"].keys())
    assert cluster_nodes == target_node_names, (
        f"Cluster nodes {cluster_nodes} should exactly match target nodes {target_node_names}"
    )


# ---- Global shard placement tests ----

def test_all_shards_on_target_nodes(output_backup, target_config):
    target_node_names = {n["name"] for n in target_config["nodes"]}
    for collection in output_backup["collections"]:
        class_name = collection["class"]
        for shard_name, shard in collection["shardingState"]["physical"].items():
            for node in shard["belongsToNodes"]:
                assert node in target_node_names, (
                    f"Shard {shard_name} in {class_name} references non-target node '{node}'"
                )
            assert shard["owningNode"] in target_node_names, (
                f"Shard {shard_name} in {class_name} has owningNode '{shard['owningNode']}' not in target"
                )


# ---- Article collection tests ----

def test_article_replication_factor(output_backup, target_config):
    article = _get_collection(output_backup, "Article")
    max_factor = len(target_config["nodes"])
    factor = article["schema"]["replicationConfig"]["factor"]
    assert factor <= max_factor, (
        f"Article replication factor {factor} exceeds target node count {max_factor}"
    )
    assert factor == max_factor, (
        f"Article replication factor should be reduced to {max_factor}, got {factor}"
    )


def test_article_vectorizer_available(output_backup, target_config):
    article = _get_collection(output_backup, "Article")
    vectorizer = article["schema"]["vectorizer"]
    available = set(target_config["available_modules"]) | {"none"}
    assert vectorizer in available, (
        f"Article vectorizer '{vectorizer}' not available on target. Available: {available}"
    )


def test_article_vectorizer_not_contextionary(output_backup):
    article = _get_collection(output_backup, "Article")
    assert article["schema"]["vectorizer"] != "text2vec-contextionary", (
        "Article vectorizer should have been migrated from deprecated text2vec-contextionary"
    )


def test_article_cache_within_limit(output_backup, target_config):
    article = _get_collection(output_backup, "Article")
    cache = article["schema"]["vectorIndexConfig"]["vectorCacheMaxObjects"]
    limit = target_config["max_vector_cache_objects"]
    assert cache <= limit, (
        f"Article vectorCacheMaxObjects {cache} exceeds target limit {limit}"
    )


def test_article_object_count_preserved(output_backup):
    article = _get_collection(output_backup, "Article")
    total = sum(s["objectCount"] for s in article["shardingState"]["physical"].values())
    expected = 25000 + 22000 + 18500
    assert total == expected, (
        f"Article total object count {total} != expected {expected}"
    )


def test_article_shard_replica_count_matches_factor(output_backup):
    article = _get_collection(output_backup, "Article")
    factor = article["schema"]["replicationConfig"]["factor"]
    for shard_name, shard in article["shardingState"]["physical"].items():
        actual = len(shard["belongsToNodes"])
        assert actual == factor, (
            f"Article shard {shard_name} has {actual} nodes in belongsToNodes but factor is {factor}"
        )


# ---- Article PQ tests ----

def test_article_pq_segments_valid(output_backup):
    """PQ segments must evenly divide the new vector dimensions after vectorizer migration."""
    article = _get_collection(output_backup, "Article")
    vic = article["schema"]["vectorIndexConfig"]
    pq = vic.get("pq", {})
    assert pq.get("enabled") is True, "Article PQ should remain enabled after migration"
    segments = pq.get("segments")
    dims = vic.get("dimensions")
    assert segments is not None and dims is not None, (
        f"PQ segments and dimensions must be present. segments={segments}, dimensions={dims}"
    )
    assert dims % segments == 0, (
        f"Article PQ segments ({segments}) must evenly divide new dimensions ({dims}). "
        f"Original segments=15 with dimensions=300 was valid, but dimension change requires recalculation."
    )
    assert 2 <= segments <= dims // 2, (
        f"PQ segments ({segments}) should be in reasonable range [2, {dims // 2}]"
    )


# ---- Product collection tests (multi-tenant) ----

def test_product_frozen_tenant_excluded(output_backup):
    product = _get_collection(output_backup, "Product")
    tenant_names = set(product["shardingState"]["physical"].keys())
    assert "tenant-tyrell" not in tenant_names, (
        "FROZEN tenant-tyrell on removed node weaviate-2 must be excluded from output"
    )


def test_product_frozen_tenant_error_in_report(migration_report):
    errors = migration_report.get("errors", [])
    error_text = json.dumps(errors).lower()
    has_tyrell = "tyrell" in error_text
    has_frozen = "frozen" in error_text
    assert has_tyrell and has_frozen, (
        f"Migration report must contain an error about FROZEN tenant-tyrell. "
        f"Found 'tyrell': {has_tyrell}, 'frozen': {has_frozen}. Errors: {errors}"
    )


def test_product_migrated_tenant_count(output_backup):
    product = _get_collection(output_backup, "Product")
    count = len(product["shardingState"]["physical"])
    assert count == 14, (
        f"Product should have 14 tenants (15 original minus 1 frozen), got {count}"
    )


def test_product_tenant_objects_preserved(output_backup):
    product = _get_collection(output_backup, "Product")
    expected_counts = {
        "tenant-acme-corp": 3200,
        "tenant-globex": 2800,
        "tenant-initech": 1500,
        "tenant-umbrella": 2100,
        "tenant-wonka": 1800,
        "tenant-stark": 2500,
        "tenant-wayne": 1900,
        "tenant-oscorp": 2200,
        "tenant-cyberdyne": 1700,
        "tenant-weyland": 3100,
        "tenant-soylent": 1400,
        "tenant-aperture": 2500,
        "tenant-black-mesa": 1000,
        "tenant-abstergo": 0,
    }
    physical = product["shardingState"]["physical"]
    for tenant_name, expected in expected_counts.items():
        assert tenant_name in physical, f"Tenant {tenant_name} missing from output"
        actual = physical[tenant_name]["objectCount"]
        assert actual == expected, (
            f"Tenant {tenant_name} object count {actual} != expected {expected}"
        )


def test_product_all_tenants_on_target_nodes(output_backup, target_config):
    product = _get_collection(output_backup, "Product")
    target_nodes = {n["name"] for n in target_config["nodes"]}
    for tenant_name, shard in product["shardingState"]["physical"].items():
        assert shard["owningNode"] in target_nodes, (
            f"Product tenant {tenant_name} is on non-target node '{shard['owningNode']}'"
        )


def test_product_tenant_balance(output_backup, target_config):
    product = _get_collection(output_backup, "Product")
    target_nodes = [n["name"] for n in target_config["nodes"]]
    node_counts = {n: 0 for n in target_nodes}
    for shard in product["shardingState"]["physical"].values():
        node = shard["owningNode"]
        if node in node_counts:
            node_counts[node] += 1
    total = sum(node_counts.values())
    for node, count in node_counts.items():
        assert count <= 9, (
            f"Node {node} has {count}/{total} Product tenants, exceeding balance threshold of 9"
        )


# ---- SearchLog collection tests ----

def test_searchlog_shards_on_target_nodes(output_backup, target_config):
    searchlog = _get_collection(output_backup, "SearchLog")
    target_nodes = {n["name"] for n in target_config["nodes"]}
    for shard_name, shard in searchlog["shardingState"]["physical"].items():
        assert shard["owningNode"] in target_nodes, (
            f"SearchLog shard {shard_name} on non-target node '{shard['owningNode']}'"
        )


def test_searchlog_object_count_preserved(output_backup):
    searchlog = _get_collection(output_backup, "SearchLog")
    total = sum(s["objectCount"] for s in searchlog["shardingState"]["physical"].values())
    expected = 50000 + 45000
    assert total == expected, (
        f"SearchLog total object count {total} != expected {expected}"
    )


# ---- SearchLog tokenizer tests ----

def test_searchlog_tokenizer_handled(output_backup, target_config):
    """Property using unsupported tokenizer must have search indexing disabled or tokenizer changed."""
    searchlog = _get_collection(output_backup, "SearchLog")
    props = searchlog["schema"]["properties"]
    ja_props = [p for p in props if p.get("name") == "query_text_ja"]
    assert len(ja_props) == 1, "query_text_ja property should exist in output"
    ja = ja_props[0]
    supported = target_config.get("supported_tokenizers", set())
    tok = ja.get("tokenization", "")
    searchable = ja.get("indexSearchable", True)
    assert tok in supported or not searchable, (
        f"query_text_ja uses unsupported tokenizer '{tok}' with indexSearchable={searchable}. "
        f"Expected tokenization changed to a supported value or indexSearchable=false"
    )


def test_tokenizer_warning_in_report(migration_report):
    """Must warn about unsupported tokenizer kagome_ja."""
    warnings = migration_report.get("warnings", [])
    all_text = json.dumps(warnings).lower()
    assert "kagome_ja" in all_text or ("tokeniz" in all_text and "unsupported" in all_text), (
        "Expected warning about unsupported tokenizer 'kagome_ja' in SearchLog"
    )


# ---- ImageEmbed collection tests (named vectors) ----

def test_imageembed_vectorizers_available(output_backup, target_config):
    imageembed = _get_collection(output_backup, "ImageEmbed")
    available = set(target_config["available_modules"]) | {"none"}
    named_vectors = imageembed["schema"]["namedVectors"]
    for vec_name, vec_config in named_vectors.items():
        vectorizer = vec_config["vectorizer"]
        assert vectorizer in available, (
            f"ImageEmbed named vector '{vec_name}' uses unavailable vectorizer '{vectorizer}'"
        )


def test_imageembed_vectorizers_changed(output_backup):
    imageembed = _get_collection(output_backup, "ImageEmbed")
    named_vectors = imageembed["schema"]["namedVectors"]
    clip_vec = named_vectors["clip_vector"]["vectorizer"]
    desc_vec = named_vectors["description_vector"]["vectorizer"]
    assert clip_vec != "multi2vec-clip", (
        "ImageEmbed clip_vector should have been migrated from multi2vec-clip"
    )
    assert desc_vec != "text2vec-openai", (
        "ImageEmbed description_vector should have been migrated from text2vec-openai"
    )


def test_imageembed_cache_within_limit(output_backup, target_config):
    imageembed = _get_collection(output_backup, "ImageEmbed")
    limit = target_config["max_vector_cache_objects"]
    for vec_name, vec_config in imageembed["schema"]["namedVectors"].items():
        cache = vec_config["vectorIndexConfig"]["vectorCacheMaxObjects"]
        assert cache <= limit, (
            f"ImageEmbed vector '{vec_name}' vectorCacheMaxObjects {cache} exceeds limit {limit}"
        )


def test_imageembed_object_count_preserved(output_backup):
    imageembed = _get_collection(output_backup, "ImageEmbed")
    total = sum(s["objectCount"] for s in imageembed["shardingState"]["physical"].values())
    expected = 8000 + 7500
    assert total == expected, (
        f"ImageEmbed total object count {total} != expected {expected}"
    )


# ---- ImageEmbed PQ tests ----

def test_imageembed_clip_pq_valid(output_backup):
    """clip_vector PQ segments must divide new dimensions after vectorizer migration."""
    ie = _get_collection(output_backup, "ImageEmbed")
    clip = ie["schema"]["namedVectors"]["clip_vector"]
    vic = clip["vectorIndexConfig"]
    pq = vic.get("pq", {})
    if pq.get("enabled"):
        segments = pq.get("segments")
        dims = vic.get("dimensions")
        assert segments is not None and dims is not None
        assert dims % segments == 0, (
            f"ImageEmbed clip_vector PQ segments ({segments}) must divide dimensions ({dims})"
        )


# ---- Cross-reference tests ----

def test_cross_references_intact(output_backup):
    """All cross-reference dataTypes must reference collections that exist in the output."""
    collection_names = {c["class"] for c in output_backup["collections"]}
    for col in output_backup["collections"]:
        for prop in col["schema"].get("properties", []):
            for dt in prop.get("dataType", []):
                if isinstance(dt, str) and len(dt) > 0 and dt[0].isupper():
                    assert dt in collection_names, (
                        f"Cross-reference '{prop['name']}' in {col['class']} "
                        f"references '{dt}' not found in output collections"
                    )


def test_cross_reference_dimension_warning(migration_report):
    """Dimension changes in referenced collections must generate cross-reference impact warnings."""
    warnings = migration_report.get("warnings", [])
    all_text = json.dumps(warnings).lower()
    has_xref = (
        "cross-ref" in all_text or "cross_ref" in all_text or
        "crossref" in all_text or
        ("reference" in all_text and "dimension" in all_text)
    )
    assert has_xref, (
        "Expected warning about dimension changes affecting cross-reference queries. "
        "Article references ImageEmbed (dimensions change), "
        "SearchLog references Article (dimensions change)."
    )


# ---- Compaction health tests ----

def test_compaction_health_warned(migration_report):
    """Shards with compaction behind schedule or high tombstone ratios must be flagged."""
    warnings = migration_report.get("warnings", [])
    all_text = json.dumps(warnings).lower()
    assert "compaction" in all_text or "tombstone" in all_text, (
        "Expected warning about compaction backlog or tombstone buildup "
        "for shards with BEHIND compaction status"
    )


# ---- Memory budget tests ----

def test_memory_budget_warned(migration_report):
    """Migration report must include HNSW memory budget analysis when budget is configured."""
    warnings = migration_report.get("warnings", [])
    all_text = json.dumps(warnings).lower()
    has_memory = "memory" in all_text
    assert has_memory, (
        "Expected HNSW memory budget analysis in warnings. "
        "Target specifies hnsw_memory_budget_bytes_per_node and "
        "estimated usage likely exceeds it after dimension changes."
    )


# ---- Migration report tests ----

def test_migration_report_has_required_sections(migration_report):
    assert "changes" in migration_report, "Report must have 'changes' section"
    assert "warnings" in migration_report, "Report must have 'warnings' section"
    assert "errors" in migration_report, "Report must have 'errors' section"


def test_dimension_change_warnings(migration_report):
    warnings = migration_report.get("warnings", [])
    dimension_related = [
        w for w in warnings
        if "dimension" in json.dumps(w).lower()
        or "revectoriz" in json.dumps(w).lower()
    ]
    assert len(dimension_related) >= 3, (
        f"Expected at least 3 dimension change warnings "
        f"(Article 300->384, ImageEmbed clip 512->2048, ImageEmbed desc 1536->384), "
        f"got {len(dimension_related)}: {dimension_related}"
    )


def test_replica_inconsistency_warning(migration_report):
    warnings = migration_report.get("warnings", [])
    warnings_text = json.dumps(warnings).lower()
    has_inconsistency = (
        "inconsisten" in warnings_text
        or ("24891" in warnings_text and "25000" in warnings_text)
        or "mismatch" in warnings_text
    )
    assert has_inconsistency, (
        "Expected a warning about replica data inconsistency in Article shard aB1cD2eF "
        "(weaviate-2 has 24891 objects vs 25000 on other replicas)"
    )


def test_report_documents_vectorizer_changes(migration_report):
    changes = migration_report.get("changes", [])
    changes_text = json.dumps(changes).lower()
    assert "vectorizer" in changes_text or "vector" in changes_text, (
        "Report changes should document vectorizer migrations"
    )
