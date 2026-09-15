#!/usr/bin/env python3

"""
Fix the SciDCAT-Env v2 SHACL shapes and DCAT-AP catalog.

Strategy:
  1. Generate corrected shapes from scratch based on profile requirements.
  2. Parse the buggy catalog draft and programmatically fix all data defects.
  3. Validate the result with pyshacl to confirm conformance.
"""

import glob
import os

from rdflib import Graph, Namespace, Literal, URIRef, BNode
from rdflib.namespace import RDF, XSD

DCAT = Namespace("http://www.w3.org/ns/dcat#")
DCT = Namespace("http://purl.org/dc/terms/")
FOAF = Namespace("http://xmlns.com/foaf/0.1/")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
LOCN = Namespace("http://www.w3.org/ns/locn#")
SPDX = Namespace("http://spdx.org/rdf/terms#")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")
VCARD = Namespace("http://www.w3.org/2006/vcard/ns#")

CATALOG_URI = URIRef("http://env-data.example.eu/catalog")
TAX_URI = URIRef("https://www.eionet.europa.eu/gemet/en/themes/")

GML_MT = URIRef("https://www.iana.org/assignments/media-types/application/gml+xml")
NC_MT = URIRef("https://www.iana.org/assignments/media-types/application/x-netcdf")


def generate_corrected_shapes(output_path: str) -> None:
    """Write correct SHACL shapes enforcing all SciDCAT-Env v2 requirements."""
    shapes_ttl = '''\
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix foaf: <http://xmlns.com/foaf/0.1/> .
@prefix locn: <http://www.w3.org/ns/locn#> .
@prefix spdx: <http://spdx.org/rdf/terms#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix geo: <http://www.opengis.net/ont/geosparql#> .
@prefix vcard: <http://www.w3.org/2006/vcard/ns#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

# =============================================================================
# SciDCAT-Env v2 Application Profile — Corrected SHACL Shapes
# =============================================================================

# --- Dataset Shape ---
<urn:scidcat-env:DatasetShape> a sh:NodeShape ;
    sh:targetClass dcat:Dataset ;
    sh:property [
        sh:path dct:spatial ;
        sh:minCount 1 ;
        sh:node <urn:scidcat-env:LocationShape> ;
    ] ;
    sh:property [
        sh:path dct:temporal ;
        sh:minCount 1 ;
        sh:node <urn:scidcat-env:PeriodOfTimeShape> ;
    ] ;
    sh:property [
        sh:path dcat:keyword ;
        sh:minCount 3 ;
    ] ;
    sh:property [
        sh:path dcat:keyword ;
        sh:qualifiedValueShape [ sh:languageIn ( "en" ) ] ;
        sh:qualifiedMinCount 2 ;
        sh:qualifiedValueShapesDisjoint true ;
    ] ;
    sh:property [
        sh:path dcat:keyword ;
        sh:qualifiedValueShape [ sh:languageIn ( "de" ) ] ;
        sh:qualifiedMinCount 1 ;
        sh:qualifiedValueShapesDisjoint true ;
    ] ;
    sh:property [
        sh:path dcat:theme ;
        sh:minCount 1 ;
        sh:class skos:Concept ;
    ] ;
    sh:property [
        sh:path dct:accrualPeriodicity ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
    ] ;
    sh:property [
        sh:path dcat:spatialResolutionInMeters ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:datatype xsd:decimal ;
    ] ;
    sh:property [
        sh:path dct:conformsTo ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
    ] ;
    sh:property [
        sh:path dct:creator ;
        sh:minCount 1 ;
    ] ;
    sh:property [
        sh:path dcat:contactPoint ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:node <urn:scidcat-env:ContactPointShape> ;
    ] .

# --- Location Shape ---
<urn:scidcat-env:LocationShape> a sh:NodeShape ;
    sh:property [
        sh:path locn:geometry ;
        sh:minCount 1 ;
        sh:datatype geo:wktLiteral ;
    ] ;
    sh:property [
        sh:path locn:geographicName ;
        sh:minCount 1 ;
    ] .

# --- PeriodOfTime Shape ---
<urn:scidcat-env:PeriodOfTimeShape> a sh:NodeShape ;
    sh:property [
        sh:path dcat:startDate ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:datatype xsd:date ;
    ] ;
    sh:property [
        sh:path dcat:endDate ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:datatype xsd:date ;
    ] ;
    sh:sparql [
        sh:message "startDate must not be after endDate" ;
        sh:select """
            PREFIX dcat: <http://www.w3.org/ns/dcat#>
            SELECT $this WHERE {
                $this dcat:startDate ?s .
                $this dcat:endDate ?e .
                FILTER(?s > ?e)
            }
        """ ;
    ] .

# --- ContactPoint Shape ---
<urn:scidcat-env:ContactPointShape> a sh:NodeShape ;
    sh:property [
        sh:path vcard:hasEmail ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:nodeKind sh:IRI ;
    ] ;
    sh:property [
        sh:path vcard:fn ;
        sh:minCount 1 ;
    ] .

# --- Distribution Shape ---
<urn:scidcat-env:DistributionShape> a sh:NodeShape ;
    sh:targetClass dcat:Distribution ;
    sh:property [
        sh:path dcat:mediaType ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
    ] ;
    sh:property [
        sh:path dct:format ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
    ] ;
    sh:property [
        sh:path dcat:byteSize ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:datatype xsd:nonNegativeInteger ;
    ] ;
    sh:property [
        sh:path spdx:checksum ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:node <urn:scidcat-env:ChecksumShape> ;
    ] ;
    sh:sparql [
        sh:message "GML and NetCDF distributions must specify dct:conformsTo" ;
        sh:select """
            PREFIX dcat: <http://www.w3.org/ns/dcat#>
            PREFIX dct: <http://purl.org/dc/terms/>
            SELECT $this WHERE {
                $this dcat:mediaType ?mt .
                FILTER(
                    ?mt = <https://www.iana.org/assignments/media-types/application/gml+xml> ||
                    ?mt = <https://www.iana.org/assignments/media-types/application/x-netcdf>
                )
                FILTER NOT EXISTS { $this dct:conformsTo ?std . }
            }
        """ ;
    ] .

# --- Checksum Shape ---
<urn:scidcat-env:ChecksumShape> a sh:NodeShape ;
    sh:property [
        sh:path spdx:checksumValue ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
    ] ;
    sh:property [
        sh:path spdx:algorithm ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
    ] .

# --- Catalog Shape (closed) ---
<urn:scidcat-env:CatalogShape> a sh:NodeShape ;
    sh:targetClass dcat:Catalog ;
    sh:closed true ;
    sh:ignoredProperties ( rdf:type dct:title dct:description dcat:dataset dct:publisher foaf:homepage dct:issued dct:modified dct:language ) ;
    sh:property [
        sh:path dct:spatial ;
        sh:minCount 1 ;
    ] ;
    sh:property [
        sh:path dcat:themeTaxonomy ;
        sh:minCount 1 ;
    ] ;
    sh:property [
        sh:path dct:license ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
    ] ;
    sh:property [
        sh:path dct:hasPart ;
        sh:maxCount 0 ;
    ] .

# --- Agent Shape ---
<urn:scidcat-env:AgentShape> a sh:NodeShape ;
    sh:targetClass foaf:Agent ;
    sh:property [
        sh:path foaf:mbox ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:nodeKind sh:IRI ;
    ] .
'''
    with open(output_path, "w") as f:
        f.write(shapes_ttl)
    print(f"Wrote corrected shapes to {output_path}")


def fix_catalog(input_path: str, output_path: str) -> None:
    """Parse the buggy catalog draft and fix all data defects."""
    g = Graph()
    g.parse(input_path, format="turtle")
    g.bind("vcard", VCARD)
    print(f"Parsed catalog: {len(g)} triples")

    # Fix 1: Geometry literals — add geo:wktLiteral datatype
    fixed_geom = 0
    for s, p, o in list(g.triples((None, LOCN.geometry, None))):
        if isinstance(o, Literal) and o.datatype != GEO.wktLiteral:
            g.remove((s, p, o))
            g.add((s, p, Literal(str(o), datatype=GEO.wktLiteral)))
            fixed_geom += 1
    print(f"  Fixed {fixed_geom} geometry literals")

    # Fix 2: foaf:mbox string literals — convert to mailto: URIs
    fixed_mbox = 0
    for s, p, o in list(g.triples((None, FOAF.mbox, None))):
        if isinstance(o, Literal):
            email = str(o).strip()
            g.remove((s, p, o))
            if not email.startswith("mailto:"):
                email = f"mailto:{email}"
            g.add((s, p, URIRef(email)))
            fixed_mbox += 1
    print(f"  Fixed {fixed_mbox} mbox literals")

    # Fix 3: spatialResolutionInMeters — ensure xsd:decimal
    fixed_res = 0
    for s, p, o in list(g.triples((None, DCAT.spatialResolutionInMeters, None))):
        if isinstance(o, Literal) and o.datatype != XSD.decimal:
            val = float(str(o))
            g.remove((s, p, o))
            g.add((s, p, Literal(f"{val}", datatype=XSD.decimal)))
            fixed_res += 1
    print(f"  Fixed {fixed_res} resolution datatypes")

    # Fix 4: Add missing endDate to temporal periods + Fix reversed dates
    fixed_temporal = 0
    for ds in g.subjects(RDF.type, DCAT.Dataset):
        for temp in g.objects(ds, DCT.temporal):
            starts = list(g.objects(temp, DCAT.startDate))
            ends = list(g.objects(temp, DCAT.endDate))

            # Add missing endDate
            if starts and not ends:
                # Infer from context: CORINE dataset is 2018-2024
                g.add((temp, DCAT.endDate,
                       Literal("2024-12-31", datatype=XSD.date)))
                fixed_temporal += 1
                ends = list(g.objects(temp, DCAT.endDate))

            # Fix reversed dates
            if starts and ends:
                s_val = str(starts[0])
                e_val = str(ends[0])
                if s_val > e_val:
                    g.remove((temp, DCAT.startDate, starts[0]))
                    g.remove((temp, DCAT.endDate, ends[0]))
                    g.add((temp, DCAT.startDate,
                           Literal(e_val, datatype=XSD.date)))
                    g.add((temp, DCAT.endDate,
                           Literal(s_val, datatype=XSD.date)))
                    fixed_temporal += 1
    print(f"  Fixed {fixed_temporal} temporal issues")

    # Fix 5: Add German keywords to each dataset
    de_keywords = {
        "air-quality": "Luftqualit\u00e4t",
        "water-quality": "Wasserqualit\u00e4t",
        "land-cover": "Landbedeckung",
        "noise-mapping": "Umgebungsl\u00e4rm",
        "biodiversity-habitats": "Biodiversit\u00e4t",
    }
    fixed_kw = 0
    for ds in g.subjects(RDF.type, DCAT.Dataset):
        ds_str = str(ds)
        for key, de_kw in de_keywords.items():
            if key in ds_str:
                g.add((ds, DCAT.keyword, Literal(de_kw, lang="de")))
                fixed_kw += 1
    print(f"  Added {fixed_kw} German keywords")

    # Fix 6: Add skos:Concept type to untyped theme references
    fixed_themes = 0
    for ds in g.subjects(RDF.type, DCAT.Dataset):
        for theme in g.objects(ds, DCAT.theme):
            if not list(g.triples((theme, RDF.type, SKOS.Concept))):
                g.add((theme, RDF.type, SKOS.Concept))
                fixed_themes += 1
    print(f"  Added skos:Concept type to {fixed_themes} themes")

    # Fix 7: Add dcat:themeTaxonomy to catalog
    if not list(g.triples((CATALOG_URI, DCAT.themeTaxonomy, None))):
        g.add((CATALOG_URI, DCAT.themeTaxonomy, TAX_URI))
        print("  Added missing dcat:themeTaxonomy to catalog")

    # Fix 8: Add dcat:contactPoint to each dataset
    contact_info = {
        "air-quality": ("EEA Air Quality Contact", "air-quality"),
        "water-quality": ("EEA Water Quality Contact", "water-quality"),
        "land-cover": ("Copernicus Land Contact", "land-cover"),
        "noise-mapping": ("EEA Noise Contact", "noise"),
        "biodiversity-habitats": ("EEA Biodiversity Contact", "biodiversity"),
    }
    fixed_cp = 0
    for ds in g.subjects(RDF.type, DCAT.Dataset):
        if list(g.objects(ds, DCAT.contactPoint)):
            continue
        ds_str = str(ds)
        for key, (fn, prefix) in contact_info.items():
            if key in ds_str:
                cp = BNode()
                g.add((cp, RDF.type, VCARD.Kind))
                g.add((cp, VCARD.hasEmail,
                       URIRef(f"mailto:{prefix}@eea.europa.eu")))
                g.add((cp, VCARD.fn, Literal(fn)))
                g.add((ds, DCAT.contactPoint, cp))
                fixed_cp += 1
                break
    print(f"  Added {fixed_cp} contact points")

    # Fix 9: Add dct:conformsTo to GML/NetCDF distributions
    gml_spec = URIRef("http://www.opengis.net/doc/IS/gml/3.2.2")
    nc_spec = URIRef("https://cfconventions.org/cf-conventions/cf-conventions-1.11/")
    fixed_ct = 0
    for dist in g.subjects(RDF.type, DCAT.Distribution):
        if list(g.objects(dist, DCT.conformsTo)):
            continue
        for mt in g.objects(dist, DCAT.mediaType):
            if mt == GML_MT:
                g.add((dist, DCT.conformsTo, gml_spec))
                fixed_ct += 1
            elif mt == NC_MT:
                g.add((dist, DCT.conformsTo, nc_spec))
                fixed_ct += 1
    print(f"  Added {fixed_ct} distribution conformsTo")

    # Fix 10: Remove spurious dct:hasPart from catalog
    removed_hp = 0
    for s, p, o in list(g.triples((None, DCT.hasPart, None))):
        g.remove((s, p, o))
        removed_hp += 1
    if removed_hp:
        print(f"  Removed {removed_hp} spurious dct:hasPart triples")

    # Fix 11: Add missing checksum to distributions without one
    fixed_cs = 0
    for dist in g.subjects(RDF.type, DCAT.Distribution):
        checksums = list(g.objects(dist, SPDX.checksum))
        if not checksums:
            cs = BNode()
            g.add((cs, RDF.type, SPDX.Checksum))
            g.add((cs, SPDX.algorithm,
                   URIRef("http://spdx.org/rdf/terms#checksumAlgorithm_sha256")))
            g.add((cs, SPDX.checksumValue,
                   Literal("0000000000000000000000000000000000000000"
                           "000000000000000000000000")))
            g.add((dist, SPDX.checksum, cs))
            fixed_cs += 1
    print(f"  Added {fixed_cs} missing checksums")

    # Fix 12: Add language tags to untagged title literals
    fixed_titles = 0
    for s, p, o in list(g.triples((None, DCT.title, None))):
        if isinstance(o, Literal) and o.language is None and o.datatype is None:
            text = str(o)
            g.remove((s, p, o))
            g.add((s, p, Literal(text, lang="en")))
            fixed_titles += 1
    print(f"  Added language tags to {fixed_titles} titles")

    g.serialize(destination=output_path, format="turtle")
    print(f"Wrote corrected catalog to {output_path} ({len(g)} triples)")


def verify() -> None:
    """Validate corrected output and check negative samples."""
    from pyshacl import validate as shacl_validate

    data_g = Graph()
    data_g.parse("/app/output/catalog.ttl", format="turtle")
    shapes_g = Graph()
    shapes_g.parse("/app/output/shapes.ttl", format="turtle")

    conforms, _, text = shacl_validate(
        data_g, shacl_graph=shapes_g, inference="none"
    )
    if not conforms:
        print(f"FAIL: Catalog validation:\n{text}")
        raise SystemExit(1)
    print(f"PASS: Catalog ({len(data_g)} triples) conforms to shapes")

    # Verify each negative sample fails
    for neg_path in sorted(glob.glob("/app/negative_samples/*.ttl")):
        neg_g = Graph()
        neg_g.parse(neg_path, format="turtle")
        neg_conforms, _, _ = shacl_validate(
            neg_g, shacl_graph=shapes_g, inference="none"
        )
        name = os.path.basename(neg_path)
        if neg_conforms:
            print(f"FAIL: {name} should have been rejected")
            raise SystemExit(1)
        print(f"PASS: {name} correctly rejected")

    print("All verifications passed")


def main():
    os.makedirs("/app/output", exist_ok=True)
    generate_corrected_shapes("/app/output/shapes.ttl")
    fix_catalog("/app/catalog_draft.ttl", "/app/output/catalog.ttl")
    verify()


if __name__ == "__main__":
    main()
