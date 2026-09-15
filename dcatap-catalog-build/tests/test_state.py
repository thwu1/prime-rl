
import os
import json
import pytest
from rdflib import Graph, Namespace, URIRef, Literal, RDF, XSD
from rdflib.namespace import DCTERMS, FOAF
from pyshacl import validate as shacl_validate

DCAT = Namespace("http://www.w3.org/ns/dcat#")
VCARD = Namespace("http://www.w3.org/2006/vcard/ns#")
SH = Namespace("http://www.w3.org/ns/shacl#")

CATALOG_PATH = "/app/catalog_fixed.ttl"
SHAPES_PATH = "/app/advanced_shapes.ttl"
AUDIT_PATH = "/app/audit_report.json"
VALIDATE_PATH = "/app/validate.sh"

BASE = "http://env-data.europa.eu/"

NS_INIT = {
    "dcat": DCAT,
    "dct": DCTERMS,
    "foaf": FOAF,
    "vcard": VCARD,
    "rdf": RDF,
    "xsd": XSD,
}


@pytest.fixture(scope="session")
def catalog():
    g = Graph()
    g.parse(CATALOG_PATH, format="turtle")
    return g


@pytest.fixture(scope="session")
def shapes():
    g = Graph()
    g.parse(SHAPES_PATH, format="turtle")
    return g


def sparql_count(g, query):
    result = list(g.query(query, initNs=NS_INIT))
    if result:
        return int(result[0][0])
    return 0


# ============================================================
# 1. BASIC PARSING
# ============================================================

class TestParsing:
    def test_catalog_fixed_exists(self):
        assert os.path.isfile(CATALOG_PATH), f"catalog_fixed.ttl not found at {CATALOG_PATH}"

    def test_valid_turtle(self):
        g = Graph()
        g.parse(CATALOG_PATH, format="turtle")
        assert len(g) > 0

    def test_substantial_graph(self):
        g = Graph()
        g.parse(CATALOG_PATH, format="turtle")
        assert len(g) > 80, f"Fixed catalog should have substantial triples, found {len(g)}"


# ============================================================
# 2. ENTITY COUNTS (structural preservation)
# ============================================================

class TestEntityCounts:
    def test_one_catalog(self, catalog):
        count = sparql_count(catalog, """
            SELECT (COUNT(DISTINCT ?s) as ?c) WHERE { ?s a dcat:Catalog }
        """)
        assert count == 1, f"Expected 1 dcat:Catalog, found {count}"

    def test_five_datasets(self, catalog):
        count = sparql_count(catalog, """
            SELECT (COUNT(DISTINCT ?s) as ?c) WHERE { ?s a dcat:Dataset }
        """)
        assert count >= 5, f"Expected at least 5 dcat:Dataset, found {count}"

    def test_eight_distributions(self, catalog):
        count = sparql_count(catalog, """
            SELECT (COUNT(DISTINCT ?s) as ?c) WHERE { ?s a dcat:Distribution }
        """)
        assert count == 8, f"Expected 8 dcat:Distribution, found {count}"

    def test_publishers(self, catalog):
        count = sparql_count(catalog, """
            SELECT (COUNT(DISTINCT ?s) as ?c) WHERE { ?s a foaf:Agent }
        """)
        assert count >= 3, f"Expected at least 3 foaf:Agent publishers, found {count}"

    def test_one_data_service(self, catalog):
        count = sparql_count(catalog, """
            SELECT (COUNT(DISTINCT ?s) as ?c) WHERE { ?s a dcat:DataService }
        """)
        assert count == 1, f"Expected 1 dcat:DataService, found {count}"

    def test_one_dataset_series(self, catalog):
        count = sparql_count(catalog, """
            SELECT (COUNT(DISTINCT ?s) as ?c) WHERE { ?s a dcat:DatasetSeries }
        """)
        assert count == 1, f"Expected 1 dcat:DatasetSeries, found {count}"


# ============================================================
# 3. VOCABULARY ALIGNMENT FIXES
# ============================================================

class TestVocabularyFixes:
    def test_themes_correct_prefix(self, catalog):
        """Error 5: All themes must use publications.europa.eu, not data.europa.eu."""
        results = list(catalog.query("""
            SELECT DISTINCT ?theme WHERE { ?ds a dcat:Dataset . ?ds dcat:theme ?theme }
        """, initNs=NS_INIT))
        assert len(results) > 0, "No themes found"
        for row in results:
            uri = str(row[0])
            assert uri.startswith("http://publications.europa.eu/resource/authority/data-theme/"), \
                f"Theme '{uri}' uses wrong prefix"

    def test_language_uris_not_literals(self, catalog):
        """Error 6: Catalog languages must be URIs, not literals."""
        cat = URIRef(BASE + "catalog")
        langs = list(catalog.objects(cat, DCTERMS.language))
        assert len(langs) >= 2, f"Expected at least 2 languages, found {len(langs)}"
        for lang in langs:
            assert isinstance(lang, URIRef), f"Language {lang} is a literal, must be URI"
            assert str(lang).startswith("http://publications.europa.eu/resource/authority/language/"), \
                f"Language '{lang}' does not use EU authority table"

    def test_frequencies_eu_authority(self, catalog):
        """Error 7: All frequencies must use EU authority table, not Dublin Core."""
        results = list(catalog.query("""
            SELECT DISTINCT ?freq WHERE {
                ?s dct:accrualPeriodicity ?freq
            }
        """, initNs=NS_INIT))
        assert len(results) > 0, "No frequencies found"
        for row in results:
            uri = str(row[0])
            assert uri.startswith("http://publications.europa.eu/resource/authority/frequency/"), \
                f"Frequency '{uri}' is not from EU authority table"
            assert "purl.org/cld/freq" not in uri, \
                f"Frequency '{uri}' uses Dublin Core instead of EU authority"

    def test_license_eu_authority(self, catalog):
        """Error 8: Catalog license must use EU authority, not SPDX."""
        cat = URIRef(BASE + "catalog")
        licenses = list(catalog.objects(cat, DCTERMS.license))
        assert len(licenses) >= 1, "Catalog has no license"
        for lic in licenses:
            uri = str(lic)
            assert "spdx.org" not in uri, f"License '{uri}' uses SPDX instead of EU authority"
            assert uri.startswith("http://publications.europa.eu/resource/authority/licence/"), \
                f"License '{uri}' is not from EU authority table"


# ============================================================
# 4. STRUCTURAL MODELING FIXES
# ============================================================

class TestStructuralFixes:
    def test_publishers_are_agents(self, catalog):
        """Error 1: Publishers must be typed as foaf:Agent."""
        agents = set(catalog.subjects(RDF.type, FOAF.Agent))
        assert len(agents) >= 3, f"Expected at least 3 foaf:Agent, found {len(agents)}"

    def test_ds001_contactpoint_is_node(self, catalog):
        """Error 3: DS001 contactPoint must be a structured node, not a literal."""
        ds001 = URIRef(BASE + "dataset/DS001")
        cps = list(catalog.objects(ds001, DCAT.contactPoint))
        assert len(cps) >= 1, "DS001 must have at least one contactPoint"
        for cp in cps:
            assert not isinstance(cp, Literal), \
                f"DS001 contactPoint is a literal '{cp}', must be a vcard:Kind node"
            fns = list(catalog.objects(cp, VCARD.fn))
            assert len(fns) >= 1, "DS001 contactPoint must have vcard:fn"

    def test_ds002_temporal_is_period(self, catalog):
        """Error 4: DS002 temporal must be a PeriodOfTime node, not a bare date."""
        ds002 = URIRef(BASE + "dataset/DS002")
        temporals = list(catalog.objects(ds002, DCTERMS.temporal))
        assert len(temporals) >= 1, "DS002 must have dct:temporal"
        for temp in temporals:
            assert not isinstance(temp, Literal), \
                f"DS002 temporal is a literal '{temp}', must be a dct:PeriodOfTime node"
            assert (temp, RDF.type, DCTERMS.PeriodOfTime) in catalog, \
                "DS002 temporal must be typed as dct:PeriodOfTime"
            starts = list(catalog.objects(temp, DCAT.startDate))
            assert len(starts) >= 1, "PeriodOfTime must have dcat:startDate"

    def test_dataset_series_typed(self, catalog):
        """Error 13: Dataset series must have dcat:DatasetSeries type."""
        series = URIRef(BASE + "series/aq-monitoring")
        assert (series, RDF.type, DCAT.DatasetSeries) in catalog, \
            "Series must be typed as dcat:DatasetSeries"


# ============================================================
# 5. PROPERTY USAGE FIXES
# ============================================================

class TestPropertyFixes:
    def test_format_is_uri(self, catalog):
        """Error 2: dct:format must be a URI, not a literal string."""
        for s, p, o in catalog.triples((None, DCTERMS.format, None)):
            assert isinstance(o, URIRef), \
                f"dct:format on {s} is a literal '{o}', must be a URI"

    def test_access_url_is_iri(self, catalog):
        """Error 9: dcat:accessURL must be an IRI, not a literal."""
        for s, p, o in catalog.triples((None, DCAT.accessURL, None)):
            assert isinstance(o, URIRef), \
                f"accessURL on {s} is a literal '{o}', must be an IRI"

    def test_bytesize_not_bare_integer(self, catalog):
        """Error 10: dcat:byteSize must not be xsd:integer (use xsd:nonNegativeInteger)."""
        for s, p, o in catalog.triples((None, DCAT.byteSize, None)):
            assert isinstance(o, Literal), f"byteSize on {s} must be a literal"
            assert o.datatype != XSD.integer, \
                f"byteSize on {s} is xsd:integer, should be xsd:nonNegativeInteger"

    def test_endpoint_url_correct_case(self, catalog):
        """Error 11: DataService must use dcat:endpointURL (uppercase), not dcat:endpointUrl."""
        service = URIRef(BASE + "service/api")
        correct = URIRef("http://www.w3.org/ns/dcat#endpointURL")
        wrong = URIRef("http://www.w3.org/ns/dcat#endpointUrl")
        correct_vals = list(catalog.objects(service, correct))
        wrong_vals = list(catalog.objects(service, wrong))
        assert len(correct_vals) >= 1, "DataService must have dcat:endpointURL (uppercase)"
        assert len(wrong_vals) == 0, "DataService must not have dcat:endpointUrl (lowercase u)"


# ============================================================
# 6. LITERAL CORRECTNESS FIXES
# ============================================================

class TestLiteralFixes:
    def test_all_titles_have_language_tags(self, catalog):
        """Error 14: All dct:title values must have language tags."""
        for s, p, o in catalog.triples((None, DCTERMS.title, None)):
            if isinstance(o, Literal):
                assert o.language is not None, \
                    f"Title '{o}' on {s} is missing a language tag"


# ============================================================
# 7. CROSS-ENTITY FIXES
# ============================================================

class TestCrossEntity:
    def test_catalog_links_all_five_datasets(self, catalog):
        """Error 12: Catalog must link to all 5 datasets via dcat:dataset."""
        cat = URIRef(BASE + "catalog")
        linked = set(str(o) for o in catalog.objects(cat, DCAT.dataset))
        for i in range(1, 6):
            ds_uri = f"{BASE}dataset/DS00{i}"
            assert ds_uri in linked, f"Catalog missing link to DS00{i}"


# ============================================================
# 8. ADVANCED SHAPES TESTS
# ============================================================

class TestAdvancedShapes:
    def test_shapes_file_exists(self):
        assert os.path.isfile(SHAPES_PATH), f"advanced_shapes.ttl not found"

    def test_shapes_valid_turtle(self, shapes):
        assert len(shapes) > 0, "Shapes graph is empty"

    def test_at_least_five_target_shapes(self, shapes):
        """Must have at least 5 NodeShapes with sh:targetClass."""
        shapes_with_target = [
            s for s in shapes.subjects(RDF.type, SH.NodeShape)
            if any(shapes.objects(s, SH.targetClass))
        ]
        assert len(shapes_with_target) >= 5, \
            f"Expected at least 5 NodeShapes with targetClass, found {len(shapes_with_target)}"

    def test_fixed_catalog_passes_shapes(self, catalog, shapes):
        """The corrected catalog must conform to all advanced shapes."""
        conforms, _, report_text = shacl_validate(
            catalog, shacl_graph=shapes, inference='none'
        )
        assert conforms, f"Fixed catalog fails advanced shapes:\n{report_text}"

    def test_bad_data_no_contactpoint_rejected(self, shapes):
        """Shape 1: Dataset without contactPoint must be rejected."""
        bad_data = """
            @prefix dcat: <http://www.w3.org/ns/dcat#> .
            @prefix dct: <http://purl.org/dc/terms/> .
            @prefix foaf: <http://xmlns.com/foaf/0.1/> .

            <http://test/ds1> a dcat:Dataset ;
                dct:title "Test"@en ;
                dct:description "Test"@en ;
                dcat:distribution <http://test/dist1> .

            <http://test/dist1> a dcat:Distribution ;
                dcat:accessURL <http://test/data.csv> ;
                dct:format <http://publications.europa.eu/resource/authority/file-type/CSV> .
        """
        bad_g = Graph()
        bad_g.parse(data=bad_data, format="turtle")
        conforms, _, _ = shacl_validate(bad_g, shacl_graph=shapes, inference='none')
        assert not conforms, "Shapes should reject dataset without contactPoint"

    def test_bad_data_series_no_enddate_rejected(self, shapes):
        """Shape 3: Dataset in series without temporal endDate must be rejected."""
        bad_data = """
            @prefix dcat: <http://www.w3.org/ns/dcat#> .
            @prefix dct: <http://purl.org/dc/terms/> .
            @prefix vcard: <http://www.w3.org/2006/vcard/ns#> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

            <http://test/ds2> a dcat:Dataset ;
                dct:title "Test2"@en ;
                dct:description "Test2"@en ;
                dcat:contactPoint [
                    a vcard:Kind ;
                    vcard:fn "X" ;
                    vcard:hasEmail <mailto:x@test.org>
                ] ;
                dcat:inSeries <http://test/series1> ;
                dct:temporal [
                    a dct:PeriodOfTime ;
                    dcat:startDate "2024-01-01"^^xsd:date
                ] ;
                dcat:distribution <http://test/dist2> .

            <http://test/series1> a dcat:DatasetSeries ;
                dct:title "Series"@en .

            <http://test/dist2> a dcat:Distribution ;
                dcat:accessURL <http://test/d2.json> ;
                dct:format <http://publications.europa.eu/resource/authority/file-type/JSON_LD> .
        """
        bad_g = Graph()
        bad_g.parse(data=bad_data, format="turtle")
        conforms, _, _ = shacl_validate(bad_g, shacl_graph=shapes, inference='none')
        assert not conforms, "Shapes should reject series dataset without temporal endDate"

    def test_bad_data_orphan_distribution_rejected(self, shapes):
        """Shape 4: Distribution not referenced by any dataset must be rejected."""
        bad_data = """
            @prefix dcat: <http://www.w3.org/ns/dcat#> .
            @prefix dct: <http://purl.org/dc/terms/> .

            <http://test/orphan> a dcat:Distribution ;
                dcat:accessURL <http://test/orphan.json> ;
                dct:format <http://publications.europa.eu/resource/authority/file-type/JSON_LD> .
        """
        bad_g = Graph()
        bad_g.parse(data=bad_data, format="turtle")
        conforms, _, _ = shacl_validate(bad_g, shacl_graph=shapes, inference='none')
        assert not conforms, "Shapes should reject orphan distribution"


# ============================================================
# 9. AUDIT REPORT TESTS
# ============================================================

class TestAuditReport:
    def test_report_exists(self):
        assert os.path.isfile(AUDIT_PATH), "audit_report.json not found"

    def test_valid_json_array(self):
        with open(AUDIT_PATH) as f:
            data = json.load(f)
        assert isinstance(data, list), "Audit report must be a JSON array"

    def test_sufficient_entries(self):
        with open(AUDIT_PATH) as f:
            data = json.load(f)
        assert len(data) >= 12, f"Expected at least 12 violations, found {len(data)}"

    def test_multiple_categories(self):
        with open(AUDIT_PATH) as f:
            data = json.load(f)
        categories = set(e.get("category") for e in data)
        assert len(categories) >= 4, \
            f"Expected at least 4 different categories, found {categories}"

    def test_entry_structure(self):
        with open(AUDIT_PATH) as f:
            data = json.load(f)
        required = {"error_id", "category", "entity", "description", "fix"}
        for entry in data:
            missing = required - set(entry.keys())
            assert len(missing) == 0, \
                f"Entry {entry.get('error_id', '?')} missing fields: {missing}"


# ============================================================
# 10. VALIDATE SCRIPT
# ============================================================

class TestValidateScript:
    def test_script_exists(self):
        assert os.path.isfile(VALIDATE_PATH), "validate.sh not found"

    def test_script_executable(self):
        assert os.access(VALIDATE_PATH, os.X_OK), "validate.sh not executable"
