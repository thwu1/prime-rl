#!/usr/bin/env python3

"""
Weaviate backup migration tool.
Transforms backup metadata from a source cluster topology to a target cluster,
handling vectorizer migration, PQ segment recalculation, tokenizer validation,
cross-reference integrity, shard redistribution, replication adjustment,
multi-tenant state management, compaction health analysis, memory budget
estimation, and constraint validation.
"""

import copy
import json
import os
import sqlite3
from collections import defaultdict

import yaml


def load_json(path):
    with open(path) as f:
        return json.load(f)


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def load_compat_db(db_path):
    """Load module registry data from the SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    modules = {}
    for row in conn.execute("SELECT * FROM modules"):
        modules[row["name"]] = {
            "type": row["type"],
            "default_dimensions": row["default_dimensions"],
            "status": row["status"],
            "notes": row["notes"],
        }

    compatibility = {}
    for row in conn.execute("SELECT * FROM compatibility_map ORDER BY priority"):
        source = row["source_module"]
        if source not in compatibility:
            compatibility[source] = []
        compatibility[source].append({
            "target": row["target_module"],
            "priority": row["priority"],
        })

    conn.close()
    return {"modules": modules, "compatibility": compatibility}


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def find_replacement_vectorizer(old_vectorizer, available_modules, compat_data):
    """Find a compatible replacement vectorizer from available target modules."""
    if old_vectorizer == "none" or old_vectorizer in available_modules:
        return old_vectorizer

    candidates = compat_data["compatibility"].get(old_vectorizer, [])
    for candidate in sorted(candidates, key=lambda x: x["priority"]):
        if candidate["target"] in available_modules:
            return candidate["target"]

    return None


def get_dimensions(vectorizer_name, compat_data):
    """Get the default vector dimensions for a vectorizer module."""
    module = compat_data["modules"].get(vectorizer_name, {})
    return module.get("default_dimensions")


def find_nearest_valid_segments(target_dims, original_segments):
    """Find the factor of target_dims closest to original_segments."""
    factors = [i for i in range(2, target_dims // 2 + 1) if target_dims % i == 0]
    if not factors:
        return original_segments
    return min(factors, key=lambda f: abs(f - original_segments))


def pick_least_loaded(target_nodes, node_counts):
    """Pick the target node with the fewest current assignments."""
    best = target_nodes[0]
    best_count = node_counts[best]
    for node in target_nodes[1:]:
        if node_counts[node] < best_count:
            best = node
            best_count = node_counts[node]
    return best


def fix_pq_config(vic, old_dims, new_dims, report, class_name, vec_name=None):
    """Recalculate PQ segments if dimensions changed and segments no longer divide evenly."""
    pq = vic.get("pq", {})
    if not pq or not pq.get("enabled"):
        return

    segments = pq.get("segments")
    if segments is None:
        return

    if new_dims % segments != 0:
        new_segments = find_nearest_valid_segments(new_dims, segments)
        pq["segments"] = new_segments
        change = {
            "type": "pq_segments_recalculated",
            "collection": class_name,
            "old_segments": segments,
            "new_segments": new_segments,
            "old_dimensions": old_dims,
            "new_dimensions": new_dims,
            "message": (
                f"PQ segments recalculated for {class_name}"
                + (f".{vec_name}" if vec_name else "")
                + f": {segments} -> {new_segments} (dimensions {old_dims} -> {new_dims})"
            ),
        }
        if vec_name:
            change["named_vector"] = vec_name
        report["changes"].append(change)


def validate_tokenizers(schema, supported_tokenizers, report, class_name):
    """Check each property's tokenizer against the target's supported list."""
    for prop in schema.get("properties", []):
        tokenization = prop.get("tokenization")
        if not tokenization:
            continue

        # Skip cross-reference properties (dataType is a class name)
        data_types = prop.get("dataType", [])
        if any(isinstance(dt, str) and len(dt) > 0 and dt[0].isupper() for dt in data_types):
            continue

        if tokenization not in supported_tokenizers:
            prop["indexSearchable"] = False
            report["warnings"].append({
                "type": "unsupported_tokenizer",
                "collection": class_name,
                "property": prop["name"],
                "tokenizer": tokenization,
                "message": (
                    f"Property '{prop['name']}' in {class_name} uses unsupported "
                    f"tokenizer '{tokenization}'. Search indexing disabled for this property. "
                    f"Supported tokenizers: {sorted(supported_tokenizers)}"
                ),
            })


def check_compaction_health(collection, report, class_name):
    """Flag shards with compaction issues or high tombstone ratios."""
    for shard_name, shard in collection["shardingState"]["physical"].items():
        tombstones = shard.get("tombstoneCount", 0)
        objects = shard.get("objectCount", 0)
        compaction = shard.get("compactionStatus")

        if compaction == "BEHIND" or (objects > 0 and tombstones > 0 and tombstones / objects > 0.1):
            ratio = f"{tombstones / objects:.1%}" if objects > 0 else "N/A"
            report["warnings"].append({
                "type": "compaction_behind",
                "collection": class_name,
                "shard": shard_name,
                "tombstone_count": tombstones,
                "object_count": objects,
                "tombstone_ratio": ratio,
                "compaction_status": compaction,
                "message": (
                    f"Shard '{shard_name}' in {class_name} has {tombstones} tombstones "
                    f"(ratio {ratio} of {objects} objects) with compaction status "
                    f"'{compaction}'. High tombstone ratio may cause elevated memory "
                    f"usage and degraded performance after restore."
                ),
            })


def validate_cross_references(output_collections, dimension_changes, report):
    """Validate cross-reference integrity and warn about dimension change impacts."""
    collection_names = {c["class"] for c in output_collections}

    for col in output_collections:
        class_name = col["class"]
        for prop in col["schema"].get("properties", []):
            for dt in prop.get("dataType", []):
                if not isinstance(dt, str) or len(dt) == 0 or not dt[0].isupper():
                    continue

                # Check target collection exists
                if dt not in collection_names:
                    report["errors"].append({
                        "type": "broken_cross_reference",
                        "collection": class_name,
                        "property": prop["name"],
                        "target_class": dt,
                        "message": (
                            f"Cross-reference '{prop['name']}' in {class_name} "
                            f"references non-existent collection '{dt}'"
                        ),
                    })
                    continue

                # Warn if referenced collection had dimension changes
                if dt in dimension_changes:
                    for vec_label, old_dim, new_dim in dimension_changes[dt]:
                        context = f".{vec_label}" if vec_label else ""
                        report["warnings"].append({
                            "type": "cross_reference_dimension_impact",
                            "collection": class_name,
                            "property": prop["name"],
                            "referenced_collection": dt,
                            "referenced_vector": vec_label or "default",
                            "old_dimensions": old_dim,
                            "new_dimensions": new_dim,
                            "message": (
                                f"Cross-reference '{prop['name']}' in {class_name} targets "
                                f"{dt}{context} whose dimensions changed from {old_dim} to "
                                f"{new_dim}. Queries traversing this reference will operate "
                                f"in a different vector space after re-vectorization."
                            ),
                        })


def calculate_hnsw_memory(output_collections, target_nodes, budget, report):
    """Calculate per-node HNSW memory usage and warn if budget is exceeded."""
    if budget is None:
        return

    node_memory = {n: 0 for n in target_nodes}

    for col in output_collections:
        schema = col["schema"]
        vic = schema.get("vectorIndexConfig", {})

        # Skip collections with no vector index
        if vic.get("skip"):
            continue

        named_vectors = schema.get("namedVectors", {})

        for shard_name, shard in col["shardingState"]["physical"].items():
            obj_count = shard["objectCount"]
            if obj_count == 0:
                continue

            # Calculate memory per object
            if named_vectors:
                mem_per_obj = 0
                for vec_name, vec_config in named_vectors.items():
                    vvic = vec_config.get("vectorIndexConfig", {})
                    dims = vvic.get("dimensions", 0)
                    max_conn = vvic.get("maxConnections", 32)
                    mem_per_obj += dims * 4 + max_conn * 16
            else:
                dims = vic.get("dimensions", 0)
                max_conn = vic.get("maxConnections", 32)
                mem_per_obj = dims * 4 + max_conn * 16

            shard_memory = obj_count * mem_per_obj

            for node in shard["belongsToNodes"]:
                if node in node_memory:
                    node_memory[node] += shard_memory

    for node, mem in sorted(node_memory.items()):
        if mem > budget:
            report["warnings"].append({
                "type": "memory_budget_exceeded",
                "node": node,
                "estimated_hnsw_bytes": mem,
                "budget_bytes": budget,
                "message": (
                    f"Node '{node}' estimated HNSW memory ({mem:,} bytes, "
                    f"{mem / (1024 ** 2):.1f} MB) exceeds budget "
                    f"({budget:,} bytes, {budget / (1024 ** 2):.1f} MB). "
                    f"Consider reducing replication factor or redistributing shards."
                ),
            })
        else:
            report["warnings"].append({
                "type": "memory_budget_ok",
                "node": node,
                "estimated_hnsw_bytes": mem,
                "budget_bytes": budget,
                "message": (
                    f"Node '{node}' estimated HNSW memory: {mem:,} bytes "
                    f"({mem / (1024 ** 2):.1f} MB) within budget of "
                    f"{budget:,} bytes ({budget / (1024 ** 2):.1f} MB)."
                ),
            })


def migrate_vectorizer_single(schema, available_modules, compat, report, class_name,
                              max_cache, dimension_changes):
    """Migrate a single (non-named) vectorizer and its HNSW config."""
    old_vec = schema.get("vectorizer", "none")
    if old_vec != "none" and old_vec not in available_modules:
        new_vec = find_replacement_vectorizer(old_vec, available_modules, compat)
        if new_vec and new_vec != old_vec:
            old_dims = get_dimensions(old_vec, compat)
            new_dims = get_dimensions(new_vec, compat)
            schema["vectorizer"] = new_vec
            if new_dims is not None and "vectorIndexConfig" in schema:
                schema["vectorIndexConfig"]["dimensions"] = new_dims
            report["changes"].append({
                "type": "vectorizer_change",
                "collection": class_name,
                "old_vectorizer": old_vec,
                "new_vectorizer": new_vec,
            })
            if old_dims and new_dims and old_dims != new_dims:
                report["warnings"].append({
                    "type": "dimension_change",
                    "collection": class_name,
                    "old_dimensions": old_dims,
                    "new_dimensions": new_dims,
                    "message": (
                        f"Re-vectorization required for {class_name}: "
                        f"{old_vec} ({old_dims}d) -> {new_vec} ({new_dims}d)"
                    ),
                })
                # Track dimension change for cross-reference analysis
                if class_name not in dimension_changes:
                    dimension_changes[class_name] = []
                dimension_changes[class_name].append((None, old_dims, new_dims))

                # Fix PQ segments if needed
                fix_pq_config(schema["vectorIndexConfig"], old_dims, new_dims,
                              report, class_name)

        elif new_vec is None:
            report["errors"].append({
                "type": "no_compatible_vectorizer",
                "collection": class_name,
                "original_vectorizer": old_vec,
                "message": f"No compatible replacement found for '{old_vec}' on target cluster",
            })

    # Cap vector cache
    vic = schema.get("vectorIndexConfig", {})
    if vic.get("vectorCacheMaxObjects", 0) > max_cache:
        old_cache = vic["vectorCacheMaxObjects"]
        vic["vectorCacheMaxObjects"] = max_cache
        report["changes"].append({
            "type": "cache_limit_reduced",
            "collection": class_name,
            "old_value": old_cache,
            "new_value": max_cache,
        })


def migrate_named_vectors(schema, available_modules, compat, report, class_name,
                          max_cache, dimension_changes):
    """Migrate named vector configurations independently."""
    named_vectors = schema.get("namedVectors", {})
    for vec_name, vec_config in named_vectors.items():
        old_vec = vec_config.get("vectorizer", "none")
        if old_vec != "none" and old_vec not in available_modules:
            new_vec = find_replacement_vectorizer(old_vec, available_modules, compat)
            if new_vec and new_vec != old_vec:
                old_dims = get_dimensions(old_vec, compat)
                new_dims = get_dimensions(new_vec, compat)
                vec_config["vectorizer"] = new_vec
                if new_dims is not None and "vectorIndexConfig" in vec_config:
                    vec_config["vectorIndexConfig"]["dimensions"] = new_dims
                report["changes"].append({
                    "type": "vectorizer_change",
                    "collection": class_name,
                    "named_vector": vec_name,
                    "old_vectorizer": old_vec,
                    "new_vectorizer": new_vec,
                })
                if old_dims and new_dims and old_dims != new_dims:
                    report["warnings"].append({
                        "type": "dimension_change",
                        "collection": class_name,
                        "named_vector": vec_name,
                        "old_dimensions": old_dims,
                        "new_dimensions": new_dims,
                        "message": (
                            f"Re-vectorization required for {class_name}.{vec_name}: "
                            f"{old_vec} ({old_dims}d) -> {new_vec} ({new_dims}d)"
                        ),
                    })
                    # Track dimension change for cross-reference analysis
                    if class_name not in dimension_changes:
                        dimension_changes[class_name] = []
                    dimension_changes[class_name].append((vec_name, old_dims, new_dims))

                    # Fix PQ segments if needed
                    fix_pq_config(vec_config["vectorIndexConfig"], old_dims, new_dims,
                                  report, class_name, vec_name)

            elif new_vec is None:
                report["errors"].append({
                    "type": "no_compatible_vectorizer",
                    "collection": class_name,
                    "named_vector": vec_name,
                    "original_vectorizer": old_vec,
                    "message": (
                        f"No compatible replacement for '{old_vec}' "
                        f"in named vector '{vec_name}'"
                    ),
                })

        # Cap cache per named vector
        vic = vec_config.get("vectorIndexConfig", {})
        if vic.get("vectorCacheMaxObjects", 0) > max_cache:
            old_cache = vic["vectorCacheMaxObjects"]
            vic["vectorCacheMaxObjects"] = max_cache
            report["changes"].append({
                "type": "cache_limit_reduced",
                "collection": class_name,
                "named_vector": vec_name,
                "old_value": old_cache,
                "new_value": max_cache,
            })


def reassign_regular_shards(sharding, schema, target_nodes, target_set, report,
                            class_name, node_counts):
    """Reassign shards for a non-multi-tenant collection."""
    new_factor = schema.get("replicationConfig", {}).get("factor", 1)

    for shard_name, shard in sharding["physical"].items():
        old_nodes = list(shard["belongsToNodes"])
        old_owner = shard["owningNode"]

        # Detect replica inconsistencies before any remapping
        replica_counts = shard.get("replicaObjectCounts", {})
        if replica_counts:
            unique_vals = set(replica_counts.values())
            if len(unique_vals) > 1:
                report["warnings"].append({
                    "type": "replica_inconsistency",
                    "collection": class_name,
                    "shard": shard_name,
                    "replica_object_counts": dict(replica_counts),
                    "message": (
                        f"Data inconsistency: shard {shard_name} replicas have "
                        f"different object counts: {dict(replica_counts)}"
                    ),
                })

        # Keep replicas that are already on target nodes
        surviving = [n for n in old_nodes if n in target_set]

        # Build the new node list up to new_factor
        new_nodes = list(surviving[:new_factor])
        if len(new_nodes) < new_factor:
            for tn in target_nodes:
                if tn not in new_nodes:
                    new_nodes.append(tn)
                    report["warnings"].append({
                        "type": "new_replica_needed",
                        "collection": class_name,
                        "shard": shard_name,
                        "node": tn,
                        "message": (
                            f"New replica for shard '{shard_name}' on '{tn}' — "
                            f"sync required after restore"
                        ),
                    })
                    if len(new_nodes) >= new_factor:
                        break

        shard["belongsToNodes"] = new_nodes

        # Update owning node
        if old_owner in target_set:
            shard["owningNode"] = old_owner
        else:
            if surviving:
                shard["owningNode"] = surviving[0]
            else:
                shard["owningNode"] = new_nodes[0]
            report["changes"].append({
                "type": "owning_node_changed",
                "collection": class_name,
                "shard": shard_name,
                "old_owner": old_owner,
                "new_owner": shard["owningNode"],
            })

        # Update replicaObjectCounts to only reference target nodes
        if replica_counts:
            new_replica = {}
            for node in new_nodes:
                if node in replica_counts:
                    new_replica[node] = replica_counts[node]
                else:
                    new_replica[node] = 0
            shard["replicaObjectCounts"] = new_replica

        if set(new_nodes) != set(old_nodes):
            report["changes"].append({
                "type": "shard_reassigned",
                "collection": class_name,
                "shard": shard_name,
                "old_nodes": old_nodes,
                "new_nodes": new_nodes,
            })

        for n in new_nodes:
            node_counts[n] += 1


def reassign_tenant_shards(sharding, target_nodes, target_set, report,
                           class_name, node_counts):
    """Reassign multi-tenant shards, respecting tenant state constraints."""
    new_physical = {}

    for shard_name, shard in sharding["physical"].items():
        tenant_status = shard.get("tenantStatus", "ACTIVE")
        owning_node = shard["owningNode"]

        if owning_node not in target_set:
            if tenant_status == "FROZEN":
                report["errors"].append({
                    "type": "frozen_tenant_on_removed_node",
                    "collection": class_name,
                    "tenant": shard_name,
                    "node": owning_node,
                    "message": (
                        f"FROZEN tenant '{shard_name}' is on removed node "
                        f"'{owning_node}' and cannot be migrated. "
                        f"Manual intervention required: unfreeze tenant before "
                        f"migration or accept data loss."
                    ),
                })
                continue  # Exclude from output

            # Reassign to least-loaded node
            new_node = pick_least_loaded(target_nodes, node_counts)
            report["changes"].append({
                "type": "tenant_reassigned",
                "collection": class_name,
                "tenant": shard_name,
                "tenant_status": tenant_status,
                "old_node": owning_node,
                "new_node": new_node,
            })
            shard["owningNode"] = new_node
            shard["belongsToNodes"] = [new_node]
            node_counts[new_node] += 1
        else:
            node_counts[owning_node] += 1

        new_physical[shard_name] = shard

    sharding["physical"] = new_physical


def process_collection(collection, target_nodes, target_set, available_modules,
                       max_cache, supported_tokenizers, compat, report,
                       node_counts, dimension_changes):
    """Process a single collection: migrate vectorizers, fix PQ, validate tokenizers,
    check compaction, fix config, reassign shards."""
    col = copy.deepcopy(collection)
    schema = col["schema"]
    sharding = col["shardingState"]
    class_name = col["class"]
    is_multitenant = schema.get("multiTenancyConfig", {}).get("enabled", False)

    # Check compaction health before any modifications
    check_compaction_health(col, report, class_name)

    # Migrate vectorizer(s)
    if "namedVectors" in schema:
        migrate_named_vectors(schema, available_modules, compat, report, class_name,
                              max_cache, dimension_changes)
    else:
        migrate_vectorizer_single(schema, available_modules, compat, report, class_name,
                                  max_cache, dimension_changes)

    # Validate tokenizers against target support
    validate_tokenizers(schema, supported_tokenizers, report, class_name)

    # Adjust replication factor
    rep_config = schema.get("replicationConfig", {})
    old_factor = rep_config.get("factor", 1)
    max_factor = len(target_nodes)
    if old_factor > max_factor:
        rep_config["factor"] = max_factor
        schema["replicationConfig"] = rep_config
        report["changes"].append({
            "type": "replication_factor_reduced",
            "collection": class_name,
            "old_factor": old_factor,
            "new_factor": max_factor,
        })

    # Reassign shards
    if is_multitenant:
        reassign_tenant_shards(sharding, target_nodes, target_set, report,
                               class_name, node_counts)
    else:
        reassign_regular_shards(sharding, schema, target_nodes, target_set, report,
                                class_name, node_counts)

    return col


def migrate():
    backup = load_json("/app/backup/backup_descriptor.json")
    target = load_yaml("/app/target_config.yaml")
    compat = load_compat_db("/app/backup/modules.db")

    target_nodes = [n["name"] for n in target["nodes"]]
    target_set = set(target_nodes)
    available_modules = set(target["installed_modules"])
    max_cache = target["resources"]["max_vector_cache_objects"]
    supported_tokenizers = set(target.get("tokenizer_support", []))
    hnsw_budget = target["resources"].get("hnsw_memory_budget_bytes_per_node")

    report = {
        "source_version": backup["server_version"],
        "target_version": target["version"],
        "source_nodes": list(backup["cluster"]["nodes"].keys()),
        "target_nodes": target_nodes,
        "changes": [],
        "warnings": [],
        "errors": [],
    }

    output = {
        "id": backup["id"],
        "version": backup["version"],
        "server_version": target["version"],
        "status": "MIGRATED",
        "start_timestamp": backup["start_timestamp"],
        "completion_timestamp": backup["completion_timestamp"],
        "cluster": {
            "node_count": len(target_nodes),
            "nodes": {
                n["name"]: {"address": n["address"], "status": "ALIVE"}
                for n in target["nodes"]
            },
        },
        "collections": [],
    }

    node_counts = defaultdict(int)
    dimension_changes = {}  # class_name -> [(vec_name_or_None, old_dim, new_dim), ...]

    for collection in backup["collections"]:
        migrated = process_collection(
            collection, target_nodes, target_set, available_modules,
            max_cache, supported_tokenizers, compat, report,
            node_counts, dimension_changes,
        )
        output["collections"].append(migrated)

    # Cross-reference validation and dimension impact warnings
    validate_cross_references(output["collections"], dimension_changes, report)

    # HNSW memory budget analysis
    calculate_hnsw_memory(output["collections"], target_nodes, hnsw_budget, report)

    save_json("/app/output/backup_descriptor.json", output)
    save_json("/app/output/migration_report.json", report)

    print(f"Migration complete: {backup['server_version']} -> {target['version']}")
    print(f"  Collections migrated: {len(output['collections'])}")
    print(f"  Changes: {len(report['changes'])}")
    print(f"  Warnings: {len(report['warnings'])}")
    print(f"  Errors: {len(report['errors'])}")
    print(f"  Output: /app/output/")


if __name__ == "__main__":
    migrate()
