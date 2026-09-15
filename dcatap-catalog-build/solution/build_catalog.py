#!/usr/bin/env python3
"""Build a DCAT-AP 3.0.1 compliant catalog from portal metadata JSON."""

import json
import os
from rdflib import Graph, Namespace, URIRef, Literal, BNode, RDF, XSD
from rdflib.namespace import DCTERMS, FOAF

DCAT = Namespace("http://www.w3.org/ns/dcat#")
VCARD = Namespace("http://www.w3.org/2006/vcard/ns#")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
SH = Namespace("http://www.w3.org/ns/shacl#")

BASE = "http://env-data.europa.eu/"
EX_SHAPES = Namespace("http://env-data.europa.eu/shapes/")

# Complete vocabulary mappings including values missing from vocab_mappings.json.
# Missing mappings were inferred from the EU Publications Office authority table
# URI pattern: http://publications.europa.eu/resource/authority/{table}/{CODE}
THEME_MAP = {
    "environment": "http://publications.europa.eu/resource/authority/data-theme/ENVI",
    "health": "http://publications.europa.eu/resource/authority/data-theme/HEAL",
    "regions": "http://publications.europa.eu/resource/authority/data-theme/REGI",
    "economy": "http://publications.europa.eu/resource/authority/data-theme/ECON",
}

FREQ_MAP = {
    "hourly": "http://publications.europa.eu/resource/authority/frequency/HOURLY",
    "monthly": "http://publications.europa.eu/resource/authority/frequency/MONTHLY",
    "quarterly": "http://publications.europa.eu/resource/authority/frequency/QUARTERLY",
    "annual": "http://publications.europa.eu/resource/authority/frequency/ANNUAL",
}

FORMAT_MAP = {
    "CSV": "http://publications.europa.eu/resource/authority/file-type/CSV",
    "JSON_LD": "http://publications.europa.eu/resource/authority/file-type/JSON_LD",
    "XLSX": "http://publications.europa.eu/resource/authority/file-type/XLSX",
    "RDF_XML": "http://publications.europa.eu/resource/authority/file-type/RDF_XML",
    "GEOJSON": "http://publications.europa.eu/resource/authority/file-type/GEOJSON",
    "TIFF": "http://publications.europa.eu/resource/authority/file-type/TIFF",
}

LANG_MAP = {
    "en": "http://publications.europa.eu/resource/authority/language/ENG",
    "fr": "http://publications.europa.eu/resource/authority/language/FRA",
    "de": "http://publications.europa.eu/resource/authority/language/DEU",
}

LICENSE_MAP = {
    "Creative Commons BY 4.0": "http://publications.europa.eu/resource/authority/licence/CC_BY_4_0",
}


def make_contact_point(g, contact_data):
    """Create a vcard:Kind contact point and return its blank node."""
    cp = BNode()
    g.add((cp, RDF.type, VCARD.Kind))
    g.add((cp, VCARD.fn, Literal(contact_data["name"])))
    g.add((cp, VCARD.hasEmail, URIRef("mailto:" + contact_data["email"])))
    return cp


def build_catalog():
    with open("/app/portal_metadata.json") as f:
        metadata = json.load(f)

    g = Graph()
    g.bind("dcat", DCAT)
    g.bind("dct", DCTERMS)
    g.bind("foaf", FOAF)
    g.bind("vcard", VCARD)
    g.bind("skos", SKOS)
    g.bind("xsd", XSD)

    portal = metadata["portal"]

    # --- Publishers ---
    pub_uris = {}
    for pub in metadata["publishers"]:
        pub_uri = URIRef(BASE + "publisher/" + pub["id"])
        pub_uris[pub["id"]] = pub_uri
        g.add((pub_uri, RDF.type, FOAF.Agent))
        for lang, name in pub["name"].items():
            g.add((pub_uri, FOAF.name, Literal(name, lang=lang)))
        if "type_uri" in pub:
            g.add((pub_uri, DCTERMS.type, URIRef(pub["type_uri"])))

    # --- Dataset Series ---
    series_uris = {}
    for series in metadata["dataset_series"]:
        ser_uri = URIRef(BASE + "series/" + series["id"])
        series_uris[series["id"]] = ser_uri
        g.add((ser_uri, RDF.type, DCAT.DatasetSeries))
        for lang, title in series["title"].items():
            g.add((ser_uri, DCTERMS.title, Literal(title, lang=lang)))
        for lang, desc in series["description"].items():
            g.add((ser_uri, DCTERMS.description, Literal(desc, lang=lang)))
        g.add((ser_uri, DCTERMS.publisher, pub_uris[series["publisher_id"]]))
        g.add((ser_uri, DCTERMS.accrualPeriodicity, URIRef(FREQ_MAP[series["frequency"]])))
        g.add((ser_uri, DCTERMS.spatial, URIRef(series["spatial_uri"])))

    # --- Catalog ---
    cat_uri = URIRef(BASE + "catalog")
    g.add((cat_uri, RDF.type, DCAT.Catalog))
    for lang, title in portal["title"].items():
        g.add((cat_uri, DCTERMS.title, Literal(title, lang=lang)))
    for lang, desc in portal["description"].items():
        g.add((cat_uri, DCTERMS.description, Literal(desc, lang=lang)))
    g.add((cat_uri, DCTERMS.publisher, pub_uris[portal["publisher_id"]]))
    g.add((cat_uri, FOAF.homepage, URIRef(portal["homepage"])))
    for lang_code in portal["languages"]:
        g.add((cat_uri, DCTERMS.language, URIRef(LANG_MAP[lang_code])))
    g.add((cat_uri, DCTERMS.spatial, URIRef(portal["spatial_uri"])))
    g.add((cat_uri, DCAT.themeTaxonomy, URIRef(portal["themes_taxonomy"])))
    g.add((cat_uri, DCTERMS.issued, Literal(portal["issued"], datatype=XSD.date)))
    g.add((cat_uri, DCTERMS.modified, Literal(portal["modified"], datatype=XSD.date)))
    g.add((cat_uri, DCTERMS.license, URIRef(LICENSE_MAP[portal["license"]])))
    cat_cp = make_contact_point(g, portal["contact"])
    g.add((cat_uri, DCAT.contactPoint, cat_cp))

    # --- Datasets ---
    ds_uris = {}
    for ds in metadata["datasets"]:
        ds_uri = URIRef(BASE + "dataset/" + ds["id"])
        ds_uris[ds["id"]] = ds_uri
        g.add((ds_uri, RDF.type, DCAT.Dataset))

        for lang, title in ds["title"].items():
            g.add((ds_uri, DCTERMS.title, Literal(title, lang=lang)))
        for lang, desc in ds["description"].items():
            g.add((ds_uri, DCTERMS.description, Literal(desc, lang=lang)))

        g.add((ds_uri, DCTERMS.publisher, pub_uris[ds["publisher_id"]]))

        for theme in ds["themes"]:
            g.add((ds_uri, DCAT.theme, URIRef(THEME_MAP[theme])))

        for lang, kws in ds["keywords"].items():
            for kw in kws:
                g.add((ds_uri, DCAT.keyword, Literal(kw, lang=lang)))

        g.add((ds_uri, DCTERMS.accrualPeriodicity, URIRef(FREQ_MAP[ds["frequency"]])))
        g.add((ds_uri, DCTERMS.spatial, URIRef(ds["spatial_uri"])))

        if "temporal_start" in ds:
            period = BNode()
            g.add((period, RDF.type, DCTERMS.PeriodOfTime))
            g.add((period, DCAT.startDate, Literal(ds["temporal_start"], datatype=XSD.date)))
            if "temporal_end" in ds:
                g.add((period, DCAT.endDate, Literal(ds["temporal_end"], datatype=XSD.date)))
            g.add((ds_uri, DCTERMS.temporal, period))

        if "landing_page" in ds:
            g.add((ds_uri, DCAT.landingPage, URIRef(ds["landing_page"])))

        ds_cp = make_contact_point(g, ds["contact"])
        g.add((ds_uri, DCAT.contactPoint, ds_cp))

        if "in_series" in ds:
            g.add((ds_uri, DCAT.inSeries, series_uris[ds["in_series"]]))

        for dist in ds["distributions"]:
            dist_uri = URIRef(BASE + "distribution/" + dist["id"])
            g.add((dist_uri, RDF.type, DCAT.Distribution))

            for lang, title in dist["title"].items():
                g.add((dist_uri, DCTERMS.title, Literal(title, lang=lang)))
            if "description" in dist:
                for lang, desc in dist["description"].items():
                    g.add((dist_uri, DCTERMS.description, Literal(desc, lang=lang)))

            g.add((dist_uri, DCAT.accessURL, URIRef(dist["access_url"])))
            if "download_url" in dist:
                g.add((dist_uri, DCAT.downloadURL, URIRef(dist["download_url"])))

            g.add((dist_uri, DCTERMS.format, URIRef(FORMAT_MAP[dist["format"]])))

            if "media_type" in dist:
                g.add((dist_uri, DCAT.mediaType,
                       URIRef("https://www.iana.org/assignments/media-types/" + dist["media_type"])))

            if "byte_size" in dist:
                g.add((dist_uri, DCAT.byteSize,
                       Literal(dist["byte_size"], datatype=XSD.nonNegativeInteger)))

            g.add((dist_uri, DCTERMS.license, URIRef(LICENSE_MAP[dist["license"]])))

            if "availability" in dist:
                g.add((dist_uri, URIRef("http://data.europa.eu/r5r/availability"),
                       URIRef(dist["availability"])))

            g.add((ds_uri, DCAT.distribution, dist_uri))

        g.add((cat_uri, DCAT.dataset, ds_uri))

    # --- Data Services ---
    for svc in metadata["data_services"]:
        svc_uri = URIRef(BASE + "service/" + svc["id"])
        g.add((svc_uri, RDF.type, DCAT.DataService))

        for lang, title in svc["title"].items():
            g.add((svc_uri, DCTERMS.title, Literal(title, lang=lang)))
        for lang, desc in svc["description"].items():
            g.add((svc_uri, DCTERMS.description, Literal(desc, lang=lang)))

        g.add((svc_uri, DCAT.endpointURL, URIRef(svc["endpoint_url"])))
        if "endpoint_description" in svc:
            g.add((svc_uri, DCAT.endpointDescription, URIRef(svc["endpoint_description"])))

        for ds_id in svc["serves_datasets"]:
            g.add((svc_uri, DCAT.servesDataset, ds_uris[ds_id]))

        g.add((svc_uri, DCTERMS.publisher, pub_uris[svc["publisher_id"]]))

        for theme in svc.get("themes", []):
            g.add((svc_uri, DCAT.theme, URIRef(THEME_MAP[theme])))

        g.add((svc_uri, DCTERMS.license, URIRef(LICENSE_MAP[svc["license"]])))

        svc_cp = make_contact_point(g, svc["contact"])
        g.add((svc_uri, DCAT.contactPoint, svc_cp))

        g.add((cat_uri, DCAT.service, svc_uri))

    g.serialize(destination="/app/catalog.ttl", format="turtle")
    print(f"Catalog written to /app/catalog.ttl ({len(g)} triples)")


def build_custom_shapes():
    """Build SHACL shapes enforcing three domain-specific business rules."""
    g = Graph()
    g.bind("sh", SH)
    g.bind("dcat", DCAT)
    g.bind("dct", DCTERMS)
    g.bind("vcard", VCARD)
    g.bind("xsd", XSD)
    g.bind("ex", EX_SHAPES)

    # --- Prefix declarations for SPARQL-based constraints ---
    prefixes = EX_SHAPES.PrefixDeclarations
    decl1 = BNode()
    g.add((prefixes, SH.declare, decl1))
    g.add((decl1, SH.prefix, Literal("dct")))
    g.add((decl1, SH.namespace, Literal("http://purl.org/dc/terms/", datatype=XSD.anyURI)))
    decl2 = BNode()
    g.add((prefixes, SH.declare, decl2))
    g.add((decl2, SH.prefix, Literal("dcat")))
    g.add((decl2, SH.namespace, Literal("http://www.w3.org/ns/dcat#", datatype=XSD.anyURI)))

    # --- Rule 1: Every dataset must have a contactPoint with vcard:fn ---
    rule1 = EX_SHAPES.DatasetContactPointRule
    g.add((rule1, RDF.type, SH.NodeShape))
    g.add((rule1, SH.targetClass, DCAT.Dataset))

    prop1a = BNode()
    g.add((rule1, SH.property, prop1a))
    g.add((prop1a, SH.path, DCAT.contactPoint))
    g.add((prop1a, SH.minCount, Literal(1)))
    g.add((prop1a, SH.message, Literal("Every dataset must have at least one contact point.")))

    prop1b = BNode()
    g.add((rule1, SH.property, prop1b))
    g.add((prop1b, SH.path, DCAT.contactPoint))
    g.add((prop1b, SH.node, EX_SHAPES.ContactPointNameShape))
    g.add((prop1b, SH.message, Literal("Contact point must have a name (vcard:fn).")))

    cp_shape = EX_SHAPES.ContactPointNameShape
    g.add((cp_shape, RDF.type, SH.NodeShape))
    prop1c = BNode()
    g.add((cp_shape, SH.property, prop1c))
    g.add((prop1c, SH.path, VCARD.fn))
    g.add((prop1c, SH.minCount, Literal(1)))
    g.add((prop1c, SH.message, Literal("Contact point must provide a name via vcard:fn.")))

    # --- Rule 2: CSV distributions must have byteSize (SPARQL-based) ---
    rule2 = EX_SHAPES.CsvByteSizeRule
    g.add((rule2, RDF.type, SH.NodeShape))
    g.add((rule2, SH.targetClass, DCAT.Distribution))
    sparql2 = BNode()
    g.add((rule2, SH.sparql, sparql2))
    g.add((sparql2, SH.message, Literal("CSV distributions must specify dcat:byteSize.")))
    g.add((sparql2, SH.prefixes, prefixes))
    g.add((sparql2, SH.select, Literal(
        "SELECT $this WHERE { "
        "$this dct:format <http://publications.europa.eu/resource/authority/file-type/CSV> . "
        "FILTER NOT EXISTS { $this dcat:byteSize ?size } "
        "}"
    )))

    # --- Rule 3: Datasets in a series must have temporal coverage (SPARQL-based) ---
    rule3 = EX_SHAPES.SeriesTemporalRule
    g.add((rule3, RDF.type, SH.NodeShape))
    g.add((rule3, SH.targetClass, DCAT.Dataset))
    sparql3 = BNode()
    g.add((rule3, SH.sparql, sparql3))
    g.add((sparql3, SH.message, Literal("Datasets in a series must have temporal coverage (dct:temporal).")))
    g.add((sparql3, SH.prefixes, prefixes))
    g.add((sparql3, SH.select, Literal(
        "SELECT $this WHERE { "
        "$this dcat:inSeries ?series . "
        "FILTER NOT EXISTS { $this dct:temporal ?period } "
        "}"
    )))

    g.serialize(destination="/app/custom_shapes.ttl", format="turtle")
    print("Custom shapes written to /app/custom_shapes.ttl")


def build_validate_script():
    """Write a validation shell script."""
    script_content = """#!/bin/bash
# Validate catalog against custom SHACL shapes
set -e

python3 -m pip install rdflib==7.1.4 pyshacl==0.26.0 -q 2>/dev/null

python3 - <<'PYEOF'
from rdflib import Graph
from pyshacl import validate

print("=== Parsing catalog.ttl ===")
data = Graph()
data.parse("/app/catalog.ttl", format="turtle")
print(f"Successfully parsed {len(data)} triples.")

print("")
print("=== Validating against custom shapes ===")
shapes = Graph()
shapes.parse("/app/custom_shapes.ttl", format="turtle")
conforms, _, text = validate(data, shacl_graph=shapes, inference="none")
print(text)
if conforms:
    print("RESULT: PASS - Catalog conforms to all custom business rules.")
else:
    print("RESULT: FAIL - Catalog violates one or more custom business rules.")
    exit(1)
PYEOF
"""
    with open("/app/validate.sh", "w") as f:
        f.write(script_content)
    os.chmod("/app/validate.sh", 0o755)
    print("Validation script written to /app/validate.sh")


if __name__ == "__main__":
    build_catalog()
    build_custom_shapes()
    build_validate_script()
    print("All artifacts generated successfully.")
