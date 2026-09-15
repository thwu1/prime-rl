
"""CapabilityStatement gap analysis for FHIR US Core conformance.

Compares a server's CapabilityStatement against the aggregated requirements
from all US Core profiles to identify missing search parameters and
interactions per resource type.
"""


def analyze_capability_gaps(capability_statement, manifest):
    """Identify gaps between required and declared capabilities.

    For each resource type referenced by US Core profiles, aggregates
    the required search parameters and interactions, then compares
    against what the server's CapabilityStatement declares.

    Args:
        capability_statement: Parsed CapabilityStatement JSON.
        manifest: The US Core manifest with profile definitions.

    Returns:
        Tuple of (gaps_dict, required_by_type, cs_by_type) where gaps_dict
        maps resource types to their missing search params and interactions.
    """
    profiles = manifest["profiles"]

    # Build per-resource-type requirement sets from profile definitions
    required_by_type = {}
    for profile_def in profiles.values():
        rt = profile_def["resourceType"]
        required_by_type[rt] = {
            "search_params": set(profile_def.get("requiredSearchParams", [])),
            "interactions": set(profile_def.get("requiredInteractions", [])),
        }

    # Parse CapabilityStatement rest resources
    cs_by_type = {}
    for rest_entry in capability_statement.get("rest", []):
        for resource_entry in rest_entry.get("resource", []):
            rt = resource_entry.get("type", "")
            declared_sp = {
                sp["name"] for sp in resource_entry.get("searchParam", [])
            }
            declared_int = {
                i["code"] for i in resource_entry.get("interaction", [])
            }
            cs_by_type[rt] = {
                "search_params": declared_sp,
                "interactions": declared_int,
            }

    # Compute gaps: required minus declared
    gaps = {}
    for rt in sorted(required_by_type.keys()):
        required = required_by_type[rt]
        declared = cs_by_type.get(
            rt, {"search_params": set(), "interactions": set()}
        )
        missing_sp = sorted(required["search_params"] - declared["search_params"])
        missing_int = sorted(required["interactions"] - declared["interactions"])
        gaps[rt] = {
            "missing_search_params": missing_sp,
            "missing_interactions": missing_int,
        }

    return gaps, required_by_type, cs_by_type
