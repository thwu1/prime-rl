#!/usr/bin/env python3

"""
Generate SHACL shapes (shapes.ttl) and a DCAT-AP catalog (catalog.ttl)
conforming to the SciDCAT-Env application profile.
"""

import json
import os
from rdflib import Graph, Namespace, Literal, URIRef, BNode
from rdflib.namespace import RDF, XSD


# --- Namespace definitions ---
DCAT = Namespace("http://www.w3.org/ns/dcat#")
DCT = Namespace("http://purl.org/dc/terms/")
FOAF = Namespace("http://xmlns.com/foaf/0.1/")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
LOCN = Namespace("http://www.w3.org/ns/locn#")
SPDX = Namespace("http://spdx.org/rdf/terms#")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")
BASE = Namespace("http://env-data.example.eu/")


def generate_shapes(output_path: str) -> None:
    """Write the SciDCAT-Env SHACL shapes as Turtle."""
    shapes_ttl = """@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix foaf: <http://xmlns.com/foaf/0.1/> .
@prefix locn: <http://www.w3.org/ns/locn#> .
@prefix spdx: <http://spdx.org/rdf/terms#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix geo: <http://www.opengis.net/ont/geosparql#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

# =============================================================================
# SciDCAT-Env Application Profile — SHACL Shapes
# =============================================================================

# --- Dataset Shape ---
<urn:scidcat-env:DatasetShape> a sh:NodeShape ;
    sh:targetClass dcat:Dataset ;
    sh:property [
        sh:path dct:spatial ;
        sh:minCount 1 ;
        sh:node <urn:scidcat-env:LocationWithGeometryShape> ;
        sh:name "spatial coverage" ;
        sh:description "Geographic area covered, with geometry and name."@en ;
    ] ;
    sh:property [
        sh:path dct:temporal ;
        sh:minCount 1 ;
        sh:node <urn:scidcat-env:PeriodOfTimeShape> ;
        sh:name "temporal coverage" ;
        sh:description "Time period covered, with start and end dates."@en ;
    ] ;
    sh:property [
        sh:path dcat:keyword ;
        sh:minCount 3 ;
        sh:name "keywords" ;
        sh:description "At least three keywords describing the dataset."@en ;
    ] ;
    sh:property [
        sh:path dcat:theme ;
        sh:minCount 1 ;
        sh:class skos:Concept ;
        sh:name "theme" ;
        sh:description "Theme from a controlled vocabulary."@en ;
    ] ;
    sh:property [
        sh:path dct:accrualPeriodicity ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:name "accrual periodicity" ;
        sh:description "Frequency of dataset updates."@en ;
    ] ;
    sh:property [
        sh:path dcat:spatialResolutionInMeters ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:datatype xsd:decimal ;
        sh:name "spatial resolution in meters" ;
        sh:description "Spatial resolution as xsd:decimal."@en ;
    ] ;
    sh:property [
        sh:path dct:conformsTo ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:name "conforms to" ;
        sh:description "Data specification or reporting standard."@en ;
    ] ;
    sh:property [
        sh:path dct:creator ;
        sh:minCount 1 ;
        sh:name "creator" ;
        sh:description "Agent who created the dataset."@en ;
    ] .

# --- Location must have geometry AND geographic name ---
<urn:scidcat-env:LocationWithGeometryShape> a sh:NodeShape ;
    sh:property [
        sh:path locn:geometry ;
        sh:minCount 1 ;
        sh:name "geometry" ;
        sh:description "WKT geometry literal."@en ;
    ] ;
    sh:property [
        sh:path locn:geographicName ;
        sh:minCount 1 ;
        sh:name "geographic name" ;
        sh:description "Human-readable geographic name."@en ;
    ] .

# --- PeriodOfTime must have start and end dates ---
<urn:scidcat-env:PeriodOfTimeShape> a sh:NodeShape ;
    sh:property [
        sh:path dcat:startDate ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:datatype xsd:date ;
        sh:name "start date" ;
    ] ;
    sh:property [
        sh:path dcat:endDate ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:datatype xsd:date ;
        sh:name "end date" ;
    ] .

# --- Distribution Shape ---
<urn:scidcat-env:DistributionShape> a sh:NodeShape ;
    sh:targetClass dcat:Distribution ;
    sh:property [
        sh:path dcat:mediaType ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:name "media type" ;
    ] ;
    sh:property [
        sh:path dct:format ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:name "format" ;
    ] ;
    sh:property [
        sh:path dcat:byteSize ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:name "byte size" ;
    ] ;
    sh:property [
        sh:path spdx:checksum ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:node <urn:scidcat-env:ChecksumShape> ;
        sh:name "checksum" ;
        sh:description "Integrity checksum with algorithm and value."@en ;
    ] .

# --- Checksum must have value and algorithm ---
<urn:scidcat-env:ChecksumShape> a sh:NodeShape ;
    sh:property [
        sh:path spdx:checksumValue ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:name "checksum value" ;
    ] ;
    sh:property [
        sh:path spdx:algorithm ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:name "checksum algorithm" ;
    ] .

# --- Catalog Shape ---
<urn:scidcat-env:CatalogShape> a sh:NodeShape ;
    sh:targetClass dcat:Catalog ;
    sh:property [
        sh:path dct:spatial ;
        sh:minCount 1 ;
        sh:name "catalog spatial coverage" ;
    ] ;
    sh:property [
        sh:path dcat:themeTaxonomy ;
        sh:minCount 1 ;
        sh:name "theme taxonomy" ;
    ] ;
    sh:property [
        sh:path dct:license ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:name "license" ;
    ] .

# --- Agent Shape ---
<urn:scidcat-env:AgentShape> a sh:NodeShape ;
    sh:targetClass foaf:Agent ;
    sh:property [
        sh:path foaf:mbox ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:name "email" ;
        sh:description "Contact email as mailto: URI."@en ;
    ] .
"""
    with open(output_path, "w") as f:
        f.write(shapes_ttl)
    print(f"Wrote shapes to {output_path}")


def generate_catalog(data_path: str, output_path: str) -> None:
    """Read JSON input and produce a DCAT-AP catalog in Turtle."""
    with open(data_path) as f:
        data = json.load(f)

    g = Graph()
    g.bind("dcat", DCAT)
    g.bind("dct", DCT)
    g.bind("foaf", FOAF)
    g.bind("skos", SKOS)
    g.bind("locn", LOCN)
    g.bind("spdx", SPDX)
    g.bind("xsd", str(XSD))
    g.bind("geo", GEO)

    # --- Catalog ---
    catalog_uri = BASE["catalog"]
    cat = data["catalog"]
    g.add((catalog_uri, RDF.type, DCAT.Catalog))
    for lang, val in cat["title"].items():
        g.add((catalog_uri, DCT.title, Literal(val, lang=lang)))
    for lang, val in cat["description"].items():
        g.add((catalog_uri, DCT.description, Literal(val, lang=lang)))
    g.add((catalog_uri, FOAF.homepage, URIRef(cat["homepage"])))
    g.add((catalog_uri, DCT.license, URIRef(cat["license"])))

    # Catalog spatial
    cat_loc = BNode()
    g.add((cat_loc, RDF.type, DCT.Location))
    g.add((cat_loc, LOCN.geometry,
           Literal(cat["spatial_coverage"]["geometry_wkt"], datatype=GEO.wktLiteral)))
    g.add((cat_loc, LOCN.geographicName,
           Literal(cat["spatial_coverage"]["label"])))
    g.add((catalog_uri, DCT.spatial, cat_loc))

    # Theme taxonomy
    tax_uri = URIRef(cat["theme_taxonomy"]["uri"])
    g.add((tax_uri, RDF.type, SKOS.ConceptScheme))
    g.add((tax_uri, DCT.title,
           Literal(cat["theme_taxonomy"]["title"], lang="en")))
    g.add((catalog_uri, DCAT.themeTaxonomy, tax_uri))

    # --- Publisher ---
    pub = data["publisher"]
    pub_uri = URIRef(pub["uri"])
    g.add((pub_uri, RDF.type, FOAF.Agent))
    for lang, val in pub["name"].items():
        g.add((pub_uri, FOAF.name, Literal(val, lang=lang)))
    g.add((pub_uri, FOAF.mbox, URIRef(f"mailto:{pub['email']}")))
    g.add((pub_uri, DCT.type, URIRef(pub["type"])))
    g.add((catalog_uri, DCT.publisher, pub_uri))

    # --- Datasets ---
    for ds_data in data["datasets"]:
        ds_uri = BASE[f"dataset/{ds_data['id']}"]
        g.add((ds_uri, RDF.type, DCAT.Dataset))
        g.add((catalog_uri, DCAT.dataset, ds_uri))

        # Title and description
        for lang, val in ds_data["title"].items():
            g.add((ds_uri, DCT.title, Literal(val, lang=lang)))
        for lang, val in ds_data["description"].items():
            g.add((ds_uri, DCT.description, Literal(val, lang=lang)))

        # Dates
        g.add((ds_uri, DCT.issued,
               Literal(ds_data["issued"], datatype=XSD.date)))
        g.add((ds_uri, DCT.modified,
               Literal(ds_data["modified"], datatype=XSD.date)))

        # Keywords
        for kw in ds_data["keywords"]:
            g.add((ds_uri, DCAT.keyword, Literal(kw, lang="en")))

        # Themes
        for theme in ds_data["themes"]:
            theme_uri = URIRef(theme["uri"])
            g.add((theme_uri, RDF.type, SKOS.Concept))
            g.add((theme_uri, SKOS.prefLabel,
                   Literal(theme["label"], lang="en")))
            g.add((ds_uri, DCAT.theme, theme_uri))

        # Spatial
        loc = BNode()
        g.add((loc, RDF.type, DCT.Location))
        g.add((loc, LOCN.geometry,
               Literal(ds_data["spatial"]["geometry_wkt"],
                       datatype=GEO.wktLiteral)))
        g.add((loc, LOCN.geographicName,
               Literal(ds_data["spatial"]["geographic_name"])))
        g.add((ds_uri, DCT.spatial, loc))

        # Temporal
        period = BNode()
        g.add((period, RDF.type, DCT.PeriodOfTime))
        g.add((period, DCAT.startDate,
               Literal(ds_data["temporal"]["start"], datatype=XSD.date)))
        g.add((period, DCAT.endDate,
               Literal(ds_data["temporal"]["end"], datatype=XSD.date)))
        g.add((ds_uri, DCT.temporal, period))

        # Frequency
        g.add((ds_uri, DCT.accrualPeriodicity,
               URIRef(ds_data["frequency"])))

        # Spatial resolution
        g.add((ds_uri, DCAT.spatialResolutionInMeters,
               Literal(ds_data["spatial_resolution_m"], datatype=XSD.decimal)))

        # Conforms to
        std_uri = URIRef(ds_data["conforms_to"]["uri"])
        g.add((std_uri, RDF.type, DCT.Standard))
        g.add((std_uri, DCT.title,
               Literal(ds_data["conforms_to"]["title"], lang="en")))
        g.add((ds_uri, DCT.conformsTo, std_uri))

        # Creator
        creator = BNode()
        g.add((creator, RDF.type, FOAF.Agent))
        for lang, val in ds_data["creator"]["name"].items():
            g.add((creator, FOAF.name, Literal(val, lang=lang)))
        g.add((creator, FOAF.mbox,
               URIRef(f"mailto:{ds_data['creator']['email']}")))
        g.add((ds_uri, DCT.creator, creator))

        # --- Distributions ---
        for dist_data in ds_data["distributions"]:
            dist_uri = BASE[f"distribution/{dist_data['id']}"]
            g.add((dist_uri, RDF.type, DCAT.Distribution))
            g.add((ds_uri, DCAT.distribution, dist_uri))

            for lang, val in dist_data["title"].items():
                g.add((dist_uri, DCT.title, Literal(val, lang=lang)))
            g.add((dist_uri, DCAT.accessURL,
                   URIRef(dist_data["access_url"])))
            g.add((dist_uri, DCAT.downloadURL,
                   URIRef(dist_data["download_url"])))
            g.add((dist_uri, DCAT.mediaType,
                   URIRef(dist_data["media_type"])))
            g.add((dist_uri, DCT["format"],
                   URIRef(dist_data["format"])))
            g.add((dist_uri, DCAT.byteSize,
                   Literal(dist_data["byte_size"],
                           datatype=XSD.nonNegativeInteger)))

            # Checksum
            cs = BNode()
            g.add((cs, RDF.type, SPDX.Checksum))
            g.add((cs, SPDX.algorithm,
                   URIRef(dist_data["checksum"]["algorithm"])))
            g.add((cs, SPDX.checksumValue,
                   Literal(dist_data["checksum"]["value"])))
            g.add((dist_uri, SPDX.checksum, cs))

    g.serialize(destination=output_path, format="turtle")
    print(f"Wrote catalog to {output_path} ({len(g)} triples)")


def main():
    os.makedirs("/app/output", exist_ok=True)
    generate_shapes("/app/output/shapes.ttl")
    generate_catalog("/app/data/datasets.json", "/app/output/catalog.ttl")


if __name__ == "__main__":
    main()
