
import os
import pytest
from rdflib import Graph, Namespace, Literal, URIRef, BNode
from rdflib.namespace import RDF, XSD
from pyshacl import validate

DCAT = Namespace("http://www.w3.org/ns/dcat#")
DCT = Namespace("http://purl.org/dc/terms/")
FOAF = Namespace("http://xmlns.com/foaf/0.1/")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
LOCN = Namespace("http://www.w3.org/ns/locn#")
SPDX = Namespace("http://spdx.org/rdf/terms#")
SH = Namespace("http://www.w3.org/ns/shacl#")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")
VCARD = Namespace("http://www.w3.org/2006/vcard/ns#")

CATALOG_PATH = "/app/output/catalog.ttl"
SHAPES_PATH = "/app/output/shapes.ttl"
NEG_DIR = "/app/negative_samples"


@pytest.fixture(scope="module")
def catalog_graph():
    g = Graph()
    g.parse(CATALOG_PATH, format="turtle")
    return g


@pytest.fixture(scope="module")
def shapes_graph():
    g = Graph()
    g.parse(SHAPES_PATH, format="turtle")
    return g


# =====================================================================
# File existence and parseability
# =====================================================================

def test_catalog_file_exists():
    assert os.path.exists(CATALOG_PATH), f"Catalog not found at {CATALOG_PATH}"


def test_shapes_file_exists():
    assert os.path.exists(SHAPES_PATH), f"Shapes not found at {SHAPES_PATH}"


def test_catalog_parseable():
    g = Graph()
    g.parse(CATALOG_PATH, format="turtle")
    assert len(g) > 0, "Catalog graph is empty"


def test_shapes_parseable():
    g = Graph()
    g.parse(SHAPES_PATH, format="turtle")
    assert len(g) > 0, "Shapes graph is empty"


# =====================================================================
# Shape structure — target classes
# =====================================================================

def _has_shape_for_class(shapes_graph, target_class):
    for shape in shapes_graph.subjects(RDF.type, SH.NodeShape):
        targets = list(shapes_graph.objects(shape, SH.targetClass))
        if target_class in targets:
            return True
    return False


def test_shapes_target_dataset(shapes_graph):
    assert _has_shape_for_class(shapes_graph, DCAT.Dataset), \
        "No NodeShape targeting dcat:Dataset"


def test_shapes_target_distribution(shapes_graph):
    assert _has_shape_for_class(shapes_graph, DCAT.Distribution), \
        "No NodeShape targeting dcat:Distribution"


def test_shapes_target_catalog(shapes_graph):
    assert _has_shape_for_class(shapes_graph, DCAT.Catalog), \
        "No NodeShape targeting dcat:Catalog"


def test_shapes_target_agent(shapes_graph):
    assert _has_shape_for_class(shapes_graph, FOAF.Agent), \
        "No NodeShape targeting foaf:Agent"


# =====================================================================
# Shape structure — advanced SHACL features
# =====================================================================

def test_shapes_sparql_temporal_ordering(shapes_graph):
    """PeriodOfTimeShape must have an active SPARQL constraint for date ordering."""
    found = False
    for shape in shapes_graph.subjects(RDF.type, SH.NodeShape):
        for sparql_node in shapes_graph.objects(shape, SH.sparql):
            select_query = str(shapes_graph.value(sparql_node, SH.select) or "")
            if "startDate" in select_query and "endDate" in select_query:
                deactivated = shapes_graph.value(sparql_node, SH.deactivated)
                if deactivated is None or str(deactivated).lower() != "true":
                    found = True
    assert found, "No active SPARQL constraint for temporal date ordering found"


def test_shapes_qualified_german_keywords(shapes_graph):
    """DatasetShape must require >=1 German keyword via qualified value shape."""
    query = """
    PREFIX sh: <http://www.w3.org/ns/shacl#>
    PREFIX dcat: <http://www.w3.org/ns/dcat#>
    ASK {
        ?ds sh:targetClass dcat:Dataset ;
            sh:property ?prop .
        ?prop sh:path dcat:keyword ;
              sh:qualifiedValueShape ?qs ;
              sh:qualifiedMinCount ?min .
        ?qs sh:languageIn ?langs .
        ?langs rdf:rest*/rdf:first "de" .
        FILTER(?min >= 1)
    }
    """
    result = bool(shapes_graph.query(query))
    assert result, "No qualified value shape requiring >=1 German keyword"


def test_shapes_catalog_closed(shapes_graph):
    """CatalogShape must be sh:closed with sh:ignoredProperties."""
    for shape in shapes_graph.subjects(RDF.type, SH.NodeShape):
        targets = list(shapes_graph.objects(shape, SH.targetClass))
        if DCAT.Catalog in targets:
            closed_val = shapes_graph.value(shape, SH.closed)
            assert closed_val is not None and str(closed_val).lower() == "true", \
                "CatalogShape must be sh:closed true"
            ignored = shapes_graph.value(shape, SH.ignoredProperties)
            assert ignored is not None, \
                "CatalogShape must have sh:ignoredProperties"
            return
    pytest.fail("No CatalogShape found")


def test_shapes_distribution_conformsto_active(shapes_graph):
    """Distribution conditional conformsTo SPARQL must not be deactivated."""
    for shape in shapes_graph.subjects(RDF.type, SH.NodeShape):
        targets = list(shapes_graph.objects(shape, SH.targetClass))
        if DCAT.Distribution in targets:
            for sparql_node in shapes_graph.objects(shape, SH.sparql):
                select_q = str(shapes_graph.value(sparql_node, SH.select) or "")
                if "conformsTo" in select_q:
                    deactivated = shapes_graph.value(sparql_node, SH.deactivated)
                    assert deactivated is None or str(deactivated).lower() != "true", \
                        "Conditional conformsTo SPARQL must not be sh:deactivated"
                    return
    pytest.fail("No SPARQL constraint for conditional conformsTo on Distribution")


def test_shapes_checksum_uses_correct_predicate(shapes_graph):
    """ChecksumShape must use spdx:checksumValue, not spdx:checksum_value."""
    checksumValue_uri = SPDX.checksumValue
    checksum_value_uri = SPDX.checksum_value
    found_correct = False
    found_wrong = False
    for shape in shapes_graph.subjects(RDF.type, SH.NodeShape):
        for prop in shapes_graph.objects(shape, SH.property):
            path = shapes_graph.value(prop, SH.path)
            if path == checksumValue_uri:
                found_correct = True
            if path == checksum_value_uri:
                found_wrong = True
    assert found_correct, "No property shape using spdx:checksumValue"
    assert not found_wrong, "Found property shape using wrong spdx:checksum_value"


def test_shapes_contact_point_referenced(shapes_graph):
    """DatasetShape must include dcat:contactPoint property with sh:node."""
    for shape in shapes_graph.subjects(RDF.type, SH.NodeShape):
        targets = list(shapes_graph.objects(shape, SH.targetClass))
        if DCAT.Dataset in targets:
            for prop in shapes_graph.objects(shape, SH.property):
                path = shapes_graph.value(prop, SH.path)
                if path == DCAT.contactPoint:
                    node_ref = shapes_graph.value(prop, SH.node)
                    assert node_ref is not None, \
                        "contactPoint property must use sh:node"
                    return
            pytest.fail("DatasetShape missing dcat:contactPoint property")
    pytest.fail("No DatasetShape found")


# =====================================================================
# Entity counts
# =====================================================================

def test_dataset_count(catalog_graph):
    datasets = list(catalog_graph.subjects(RDF.type, DCAT.Dataset))
    assert len(datasets) == 5, f"Expected 5 datasets, got {len(datasets)}"


def test_distribution_count(catalog_graph):
    dists = list(catalog_graph.subjects(RDF.type, DCAT.Distribution))
    assert len(dists) == 8, f"Expected 8 distributions, got {len(dists)}"


def test_catalog_count(catalog_graph):
    cats = list(catalog_graph.subjects(RDF.type, DCAT.Catalog))
    assert len(cats) == 1, f"Expected 1 catalog, got {len(cats)}"


# =====================================================================
# SHACL validation — positive
# =====================================================================

def test_catalog_validates_against_shapes():
    """The corrected catalog must pass SHACL validation against corrected shapes."""
    data_g = Graph()
    data_g.parse(CATALOG_PATH, format="turtle")
    shapes_g = Graph()
    shapes_g.parse(SHAPES_PATH, format="turtle")
    conforms, _, results_text = validate(
        data_g, shacl_graph=shapes_g, inference="none"
    )
    assert conforms, f"Catalog failed SHACL validation:\n{results_text}"


# =====================================================================
# SHACL validation — negative samples
# =====================================================================

def _negative_must_fail(neg_file):
    neg_g = Graph()
    neg_g.parse(neg_file, format="turtle")
    shapes_g = Graph()
    shapes_g.parse(SHAPES_PATH, format="turtle")
    conforms, _, results_text = validate(
        neg_g, shacl_graph=shapes_g, inference="none"
    )
    return conforms, results_text


def test_negative_temporal_order():
    conforms, text = _negative_must_fail(
        os.path.join(NEG_DIR, "negative_temporal_order.ttl"))
    assert not conforms, "Shapes should reject dataset with startDate > endDate"


def test_negative_no_german_kw():
    conforms, text = _negative_must_fail(
        os.path.join(NEG_DIR, "negative_no_german_kw.ttl"))
    assert not conforms, "Shapes should reject dataset without German keywords"


def test_negative_no_spatial():
    conforms, text = _negative_must_fail(
        os.path.join(NEG_DIR, "negative_no_spatial.ttl"))
    assert not conforms, "Shapes should reject dataset without dct:spatial"


def test_negative_no_checksum():
    conforms, text = _negative_must_fail(
        os.path.join(NEG_DIR, "negative_no_checksum.ttl"))
    assert not conforms, "Shapes should reject distribution without spdx:checksum"


def test_negative_gml_no_conformsto():
    conforms, text = _negative_must_fail(
        os.path.join(NEG_DIR, "negative_gml_no_conformsto.ttl"))
    assert not conforms, "Shapes should reject GML distribution without conformsTo"


def test_negative_no_contact():
    conforms, text = _negative_must_fail(
        os.path.join(NEG_DIR, "negative_no_contact.ttl"))
    assert not conforms, "Shapes should reject dataset without dcat:contactPoint"


# =====================================================================
# Dataset property checks
# =====================================================================

def test_datasets_have_spatial(catalog_graph):
    for ds in catalog_graph.subjects(RDF.type, DCAT.Dataset):
        spatial = list(catalog_graph.objects(ds, DCT.spatial))
        assert len(spatial) >= 1, f"Dataset {ds} missing dct:spatial"


def test_datasets_have_temporal(catalog_graph):
    for ds in catalog_graph.subjects(RDF.type, DCAT.Dataset):
        temporal = list(catalog_graph.objects(ds, DCT.temporal))
        assert len(temporal) >= 1, f"Dataset {ds} missing dct:temporal"


def test_datasets_have_keywords_min_3(catalog_graph):
    for ds in catalog_graph.subjects(RDF.type, DCAT.Dataset):
        keywords = list(catalog_graph.objects(ds, DCAT.keyword))
        assert len(keywords) >= 3, \
            f"Dataset {ds} has {len(keywords)} keywords, need >= 3"


def test_datasets_have_german_keywords(catalog_graph):
    """Each dataset must have at least one German keyword."""
    for ds in catalog_graph.subjects(RDF.type, DCAT.Dataset):
        keywords = list(catalog_graph.objects(ds, DCAT.keyword))
        de_count = sum(1 for kw in keywords
                       if isinstance(kw, Literal) and kw.language == "de")
        assert de_count >= 1, f"Dataset {ds} has no German (@de) keywords"


def test_datasets_have_themes(catalog_graph):
    for ds in catalog_graph.subjects(RDF.type, DCAT.Dataset):
        themes = list(catalog_graph.objects(ds, DCAT.theme))
        assert len(themes) >= 1, f"Dataset {ds} missing dcat:theme"


def test_datasets_have_spatial_resolution(catalog_graph):
    for ds in catalog_graph.subjects(RDF.type, DCAT.Dataset):
        res = list(catalog_graph.objects(ds, DCAT.spatialResolutionInMeters))
        assert len(res) >= 1, \
            f"Dataset {ds} missing dcat:spatialResolutionInMeters"


def test_datasets_have_creator(catalog_graph):
    for ds in catalog_graph.subjects(RDF.type, DCAT.Dataset):
        creators = list(catalog_graph.objects(ds, DCT.creator))
        assert len(creators) >= 1, f"Dataset {ds} missing dct:creator"


def test_datasets_have_contact_point(catalog_graph):
    """Each dataset must have exactly one dcat:contactPoint."""
    for ds in catalog_graph.subjects(RDF.type, DCAT.Dataset):
        cps = list(catalog_graph.objects(ds, DCAT.contactPoint))
        assert len(cps) >= 1, f"Dataset {ds} missing dcat:contactPoint"


def test_temporal_dates_ordered(catalog_graph):
    """All temporal periods must have startDate <= endDate."""
    for ds in catalog_graph.subjects(RDF.type, DCAT.Dataset):
        for temp in catalog_graph.objects(ds, DCT.temporal):
            starts = list(catalog_graph.objects(temp, DCAT.startDate))
            ends = list(catalog_graph.objects(temp, DCAT.endDate))
            if starts and ends:
                s = str(starts[0])
                e = str(ends[0])
                assert s <= e, \
                    f"Dataset {ds}: startDate {s} > endDate {e}"


# =====================================================================
# Distribution property checks
# =====================================================================

def test_distributions_have_checksum(catalog_graph):
    for d in catalog_graph.subjects(RDF.type, DCAT.Distribution):
        cs = list(catalog_graph.objects(d, SPDX.checksum))
        assert len(cs) >= 1, f"Distribution {d} missing spdx:checksum"


def test_distributions_have_media_type(catalog_graph):
    for d in catalog_graph.subjects(RDF.type, DCAT.Distribution):
        mt = list(catalog_graph.objects(d, DCAT.mediaType))
        assert len(mt) >= 1, f"Distribution {d} missing dcat:mediaType"


def test_distributions_have_format(catalog_graph):
    for d in catalog_graph.subjects(RDF.type, DCAT.Distribution):
        fmt = list(catalog_graph.objects(d, DCT["format"]))
        assert len(fmt) >= 1, f"Distribution {d} missing dct:format"


def test_distributions_have_byte_size(catalog_graph):
    for d in catalog_graph.subjects(RDF.type, DCAT.Distribution):
        bs = list(catalog_graph.objects(d, DCAT.byteSize))
        assert len(bs) >= 1, f"Distribution {d} missing dcat:byteSize"


# =====================================================================
# Catalog property checks
# =====================================================================

def test_catalog_has_publisher(catalog_graph):
    for c in catalog_graph.subjects(RDF.type, DCAT.Catalog):
        pub = list(catalog_graph.objects(c, DCT.publisher))
        assert len(pub) >= 1, f"Catalog {c} missing dct:publisher"


def test_catalog_has_license(catalog_graph):
    for c in catalog_graph.subjects(RDF.type, DCAT.Catalog):
        lic = list(catalog_graph.objects(c, DCT.license))
        assert len(lic) >= 1, f"Catalog {c} missing dct:license"


def test_catalog_has_theme_taxonomy(catalog_graph):
    for c in catalog_graph.subjects(RDF.type, DCAT.Catalog):
        tax = list(catalog_graph.objects(c, DCAT.themeTaxonomy))
        assert len(tax) >= 1, f"Catalog {c} missing dcat:themeTaxonomy"


def test_catalog_no_has_part(catalog_graph):
    """Catalog must not have dct:hasPart (leaf catalog constraint)."""
    for c in catalog_graph.subjects(RDF.type, DCAT.Catalog):
        parts = list(catalog_graph.objects(c, DCT.hasPart))
        assert len(parts) == 0, \
            f"Catalog {c} must not have dct:hasPart (found {len(parts)})"


# =====================================================================
# Agent checks
# =====================================================================

def test_agents_have_mbox_as_uri(catalog_graph):
    """Agent email addresses must be mailto: URIs, not string literals."""
    agents = list(catalog_graph.subjects(RDF.type, FOAF.Agent))
    assert len(agents) >= 2, \
        f"Expected at least 2 agents (publisher + creators), got {len(agents)}"
    for agent in agents:
        mbox_values = list(catalog_graph.objects(agent, FOAF.mbox))
        assert len(mbox_values) >= 1, f"Agent {agent} missing foaf:mbox"
        for mbox in mbox_values:
            assert isinstance(mbox, URIRef), (
                f"Agent {agent} foaf:mbox is literal '{mbox}' — "
                f"must be a mailto: URI"
            )


# =====================================================================
# Multilingual checks
# =====================================================================

def test_multilingual_titles(catalog_graph):
    """Titles must include both English and German language tags."""
    has_en = any(isinstance(o, Literal) and o.language == "en"
                 for _, _, o in catalog_graph.triples((None, DCT.title, None)))
    has_de = any(isinstance(o, Literal) and o.language == "de"
                 for _, _, o in catalog_graph.triples((None, DCT.title, None)))
    assert has_en, "No English language-tagged titles found"
    assert has_de, "No German language-tagged titles found"


# =====================================================================
# Typed literal checks
# =====================================================================

def test_geometry_literals_have_wkt_datatype(catalog_graph):
    """All geometry values must be typed as geo:wktLiteral."""
    geom_count = 0
    for s, p, o in catalog_graph.triples((None, LOCN.geometry, None)):
        geom_count += 1
        assert isinstance(o, Literal), f"Geometry on {s} is not a literal"
        assert o.datatype == GEO.wktLiteral, (
            f"Geometry on {s} has datatype {o.datatype}, "
            f"expected geo:wktLiteral"
        )
    assert geom_count >= 6, \
        f"Expected at least 6 geometry values, found {geom_count}"


def test_spatial_resolution_is_decimal(catalog_graph):
    """spatialResolutionInMeters must be typed as xsd:decimal."""
    for ds in catalog_graph.subjects(RDF.type, DCAT.Dataset):
        for val in catalog_graph.objects(ds, DCAT.spatialResolutionInMeters):
            assert isinstance(val, Literal), \
                f"Resolution on {ds} is not a literal"
            assert val.datatype == XSD.decimal, (
                f"Dataset {ds} spatialResolutionInMeters has datatype "
                f"{val.datatype}, expected xsd:decimal"
            )


def test_temporal_dates_are_xsd_date(catalog_graph):
    """Temporal dates must be typed as xsd:date (not xsd:dateTime)."""
    for ds in catalog_graph.subjects(RDF.type, DCAT.Dataset):
        for temp in catalog_graph.objects(ds, DCT.temporal):
            for date_val in catalog_graph.objects(temp, DCAT.startDate):
                assert isinstance(date_val, Literal)
                assert date_val.datatype == XSD.date, (
                    f"startDate has datatype {date_val.datatype}, "
                    f"expected xsd:date"
                )
            for date_val in catalog_graph.objects(temp, DCAT.endDate):
                assert isinstance(date_val, Literal)
                assert date_val.datatype == XSD.date, (
                    f"endDate has datatype {date_val.datatype}, "
                    f"expected xsd:date"
                )


def test_dataset_locations_have_geometry_and_name(catalog_graph):
    """Each dataset's spatial location must have geometry and name."""
    for ds in catalog_graph.subjects(RDF.type, DCAT.Dataset):
        for loc in catalog_graph.objects(ds, DCT.spatial):
            geom = list(catalog_graph.objects(loc, LOCN.geometry))
            assert len(geom) >= 1, \
                f"Location on {ds} missing locn:geometry"
            name = list(catalog_graph.objects(loc, LOCN.geographicName))
            assert len(name) >= 1, \
                f"Location on {ds} missing locn:geographicName"


def test_temporal_has_start_and_end_dates(catalog_graph):
    """Each temporal coverage must have both startDate and endDate."""
    for ds in catalog_graph.subjects(RDF.type, DCAT.Dataset):
        for temp in catalog_graph.objects(ds, DCT.temporal):
            start = list(catalog_graph.objects(temp, DCAT.startDate))
            end = list(catalog_graph.objects(temp, DCAT.endDate))
            assert len(start) >= 1, \
                f"PeriodOfTime on {ds} missing dcat:startDate"
            assert len(end) >= 1, \
                f"PeriodOfTime on {ds} missing dcat:endDate"


def test_checksums_have_value_and_algorithm(catalog_graph):
    """Each checksum must have spdx:checksumValue and spdx:algorithm."""
    for dist in catalog_graph.subjects(RDF.type, DCAT.Distribution):
        for cs in catalog_graph.objects(dist, SPDX.checksum):
            val = list(catalog_graph.objects(cs, SPDX.checksumValue))
            alg = list(catalog_graph.objects(cs, SPDX.algorithm))
            assert len(val) >= 1, f"Checksum on {dist} missing spdx:checksumValue"
            assert len(alg) >= 1, f"Checksum on {dist} missing spdx:algorithm"


def test_contact_points_have_email_and_fn(catalog_graph):
    """Each dataset's contactPoint must have vcard:hasEmail (IRI) and vcard:fn."""
    for ds in catalog_graph.subjects(RDF.type, DCAT.Dataset):
        for cp in catalog_graph.objects(ds, DCAT.contactPoint):
            email = list(catalog_graph.objects(cp, VCARD.hasEmail))
            fn = list(catalog_graph.objects(cp, VCARD.fn))
            assert len(email) >= 1, \
                f"ContactPoint on {ds} missing vcard:hasEmail"
            assert len(fn) >= 1, \
                f"ContactPoint on {ds} missing vcard:fn"
            for e in email:
                assert isinstance(e, URIRef), \
                    f"ContactPoint email must be IRI, got {type(e).__name__}"


def test_gml_netcdf_have_conformsto(catalog_graph):
    """GML and NetCDF distributions must have dct:conformsTo."""
    gml_mt = URIRef(
        "https://www.iana.org/assignments/media-types/application/gml+xml")
    nc_mt = URIRef(
        "https://www.iana.org/assignments/media-types/application/x-netcdf")
    for dist in catalog_graph.subjects(RDF.type, DCAT.Distribution):
        for mt in catalog_graph.objects(dist, DCAT.mediaType):
            if mt in (gml_mt, nc_mt):
                ct = list(catalog_graph.objects(dist, DCT.conformsTo))
                assert len(ct) >= 1, (
                    f"Distribution {dist} with media type {mt} "
                    f"must have dct:conformsTo"
                )
