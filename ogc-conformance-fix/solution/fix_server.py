#!/usr/bin/env python3

"""Fix all 11 OGC API Features conformance violations in /app/server.py."""

with open('/app/server.py', 'r') as f:
    code = f.read()

# Fix 1: Landing page service-desc link relation
# The IANA registered relation is "service-desc", not "service-description"
code = code.replace(
    '"rel": "service-description",',
    '"rel": "service-desc",'
)

# Fix 2: Landing page conformance link relation
# The required relation is "conformance", not "compliance"
code = code.replace(
    '"rel": "compliance",',
    '"rel": "conformance",'
)

# Fix 3: Default CRS must use the OGC CRS84 URI
# CRS84 and EPSG:4326 share the same datum but have different axis orders
code = code.replace(
    '"crs": ["EPSG:4326"]',
    '"crs": ["http://www.opengis.net/def/crs/OGC/1.3/CRS84"]'
)

# Fix 4: Bbox coordinate order per OGC spec is [minLon, minLat, maxLon, maxLat]
# The original incorrectly destructures as [minLat, minLon, maxLat, maxLon]
code = code.replace(
    'min_lat, min_lon, max_lat, max_lon = bbox[0], bbox[1], bbox[2], bbox[3]',
    'min_lon, min_lat, max_lon, max_lat = bbox[0], bbox[1], bbox[2], bbox[3]'
)

# Fix 5: Handle open-ended datetime ranges with ".." sentinel
# The spec requires support for "../end" and "start/.."
old_datetime = """        start = isoparse(start_str)
        end = isoparse(end_str)
        return start <= feature_dt <= end"""

new_datetime = """        if start_str == '..':
            end = isoparse(end_str)
            return feature_dt <= end
        elif end_str == '..':
            start = isoparse(start_str)
            return feature_dt >= start
        else:
            start = isoparse(start_str)
            end = isoparse(end_str)
            return start <= feature_dt <= end"""

code = code.replace(old_datetime, new_datetime)

# Fix 6: Unknown query parameters must return 400
# Insert validation before limit parsing
old_parse_limit = """    # Parse limit
    limit_str = request.args.get('limit', '10')"""

new_parse_limit = """    # Validate query parameters against known set
    for param in request.args:
        if param not in KNOWN_PARAMS:
            return jsonify({
                "code": "InvalidParameterValue",
                "description": f"Unknown query parameter: {param}"
            }), 400

    # Parse limit
    limit_str = request.args.get('limit', '10')"""

code = code.replace(old_parse_limit, new_parse_limit)

# Fix 7: Invalid limit values (non-integer) must return 400
old_limit_handler = """    try:
        limit = int(limit_str)
    except (ValueError, TypeError):
        limit = 10"""

new_limit_handler = """    try:
        limit = int(limit_str)
    except (ValueError, TypeError):
        return jsonify({
            "code": "InvalidParameterValue",
            "description": f"Invalid value for limit: {limit_str}"
        }), 400"""

code = code.replace(old_limit_handler, new_limit_handler)

# Fix 8: numberReturned must equal actual count of features in the response
# The original sets it to len(filtered) (total matches) instead of len(paginated)
code = code.replace(
    '"numberReturned": number_returned',
    '"numberReturned": len(paginated)'
)

# Fix 9: Pagination next link offset has off-by-one error
# offset + limit + 1 skips one feature per page; should be offset + limit
code = code.replace(
    'next_offset = offset + limit + 1',
    'next_offset = offset + limit'
)

# Fix 10: Pagination next links must preserve active query filters (bbox, datetime)
# Without this, paginated access to filtered results breaks on page 2+
old_next_link = """    next_offset = offset + limit
    if next_offset < number_matched:
        links.append({
            "href": f"{base}/collections/{collection_id}/items?offset={next_offset}&limit={limit}",
            "rel": "next",
            "type": "application/geo+json"
        })"""

new_next_link = """    next_offset = offset + limit
    if next_offset < number_matched:
        next_params = []
        if bbox_str:
            next_params.append(f"bbox={bbox_str}")
        if datetime_param:
            next_params.append(f"datetime={datetime_param}")
        next_params.append(f"offset={next_offset}")
        next_params.append(f"limit={limit}")
        next_query = '&'.join(next_params)
        links.append({
            "href": f"{base}/collections/{collection_id}/items?{next_query}",
            "rel": "next",
            "type": "application/geo+json"
        })"""

code = code.replace(old_next_link, new_next_link)

# Fix 11: Items endpoint must return Content-Type: application/geo+json
# Flask's jsonify() returns application/json, but GeoJSON feature collections
# require application/geo+json per the OGC spec (/req/core/fc-response)
old_return = """    return jsonify({
        "type": "FeatureCollection",
        "features": paginated,
        "links": links,
        "timeStamp": datetime.now(timezone.utc).isoformat(),
        "numberMatched": number_matched,
        "numberReturned": len(paginated)
    })"""

new_return = """    result = {
        "type": "FeatureCollection",
        "features": paginated,
        "links": links,
        "timeStamp": datetime.now(timezone.utc).isoformat(),
        "numberMatched": number_matched,
        "numberReturned": len(paginated)
    }
    return Response(json.dumps(result), mimetype='application/geo+json')"""

code = code.replace(old_return, new_return)

with open('/app/server.py', 'w') as f:
    f.write(code)

print("All 11 conformance fixes applied successfully.")
