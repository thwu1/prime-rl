
import os
import pytest
from rdflib import Graph, Namespace, URIRef, Literal, BNode
from rdflib.namespace import RDF, DCTERMS, FOAF, SKOS, DCAT, XSD

VCARD = Namespace("http://www.w3.org/2006/vcard/ns#")
ELI = Namespace("http://data.europa.eu/eli/ontology#")
R5R = Namespace("http://data.europa.eu/r5r/")

OUTPUT_PATH = "/app/output/catalog.ttl"
SHAPES_PATH = "/app/shapes/dcat-ap-301.ttl"


@pytest.fixture(scope="module")
def catalog_graph():
    g = Graph()
    g.parse(OUTPUT_PATH, format="turtle")
    return g


def test_output_exists():
    assert os.path.exists(OUTPUT_PATH), f"Output file not found at {OUTPUT_PATH}"
    assert os.path.getsize(OUTPUT_PATH) > 100, "Output file is too small to be a valid catalog"


def test_valid_turtle():
    g = Graph()
    g.parse(OUTPUT_PATH, format="turtle")
    assert len(g) > 50, f"Output graph has only {len(g)} triples, expected a substantial catalog"


# --- Class constraint validation (enforces sh:class from SHACL shapes) ---

def test_class_constraints_on_referenced_resources(catalog_graph):
    """Validate sh:class constraints from SHACL shapes: every resource referenced
    via a property that has a sh:class constraint must carry the required rdf:type."""
    errors = []
    class_checks = [
        (DCTERMS.publisher, FOAF.Agent, "publisher"),
        (DCAT.theme, SKOS.Concept, "theme"),
        (DCTERMS.language, DCTERMS.LinguisticSystem, "language"),
        (DCTERMS.spatial, DCTERMS.Location, "spatial"),
        (DCAT.themeTaxonomy, SKOS.ConceptScheme, "theme taxonomy"),
        (DCTERMS.license, DCTERMS.LicenseDocument, "license"),
        (DCTERMS.temporal, DCTERMS.PeriodOfTime, "temporal"),
        (DCTERMS.accrualPeriodicity, DCTERMS.Frequency, "frequency"),
        (DCTERMS.conformsTo, DCTERMS.Standard, "conforms to"),
        (DCTERMS.accessRights, DCTERMS.RightsStatement, "access rights"),
        (DCTERMS.format, DCTERMS.MediaTypeOrExtent, "format"),
        (DCAT.mediaType, DCTERMS.MediaType, "media type"),
        (DCAT.contactPoint, VCARD.Kind, "contact point"),
        (DCAT.landingPage, FOAF.Document, "landing page"),
        (FOAF.homepage, FOAF.Document, "homepage"),
        (DCAT.distribution, DCAT.Distribution, "distribution"),
        (DCAT.dataset, DCAT.Dataset, "dataset"),
        (DCAT.service, DCAT.DataService, "service"),
        (DCAT.servesDataset, DCAT.Dataset, "serves dataset"),
        (R5R.applicableLegislation, ELI.LegalResource, "applicable legislation"),
    ]
    for prop, expected_class, desc in class_checks:
        for s, p, o in catalog_graph.triples((None, prop, None)):
            if isinstance(o, (URIRef, BNode)):
                types = set(catalog_graph.objects(o, RDF.type))
                if expected_class not in types:
                    errors.append(
                        f"{desc}: {o} referenced from {s} missing rdf:type {expected_class}"
                    )
    assert not errors, "Class constraint violations:\n" + "\n".join(errors[:20])


def test_date_literals_datatype(catalog_graph):
    """All date properties must use xsd:date datatype."""
    date_props = [DCTERMS.issued, DCTERMS.modified, DCAT.startDate, DCAT.endDate]
    errors = []
    for prop in date_props:
        for s, p, o in catalog_graph.triples((None, prop, None)):
            if isinstance(o, Literal):
                if o.datatype != XSD.date:
                    errors.append(
                        f"{s} {prop} has datatype {o.datatype}, expected xsd:date"
                    )
    assert not errors, "Date datatype violations:\n" + "\n".join(errors[:10])


# --- Entity count tests ---

def test_catalog_count(catalog_graph):
    catalogs = list(catalog_graph.subjects(RDF.type, DCAT.Catalog))
    assert len(catalogs) == 1, f"Expected exactly 1 dcat:Catalog, found {len(catalogs)}"


def test_dataset_count(catalog_graph):
    datasets = list(catalog_graph.subjects(RDF.type, DCAT.Dataset))
    assert len(datasets) == 6, f"Expected 6 dcat:Dataset instances, found {len(datasets)}"


def test_distribution_count(catalog_graph):
    distributions = list(catalog_graph.subjects(RDF.type, DCAT.Distribution))
    assert len(distributions) == 11, f"Expected 11 dcat:Distribution instances, found {len(distributions)}"


def test_dataservice_count(catalog_graph):
    services = list(catalog_graph.subjects(RDF.type, DCAT.DataService))
    assert len(services) == 2, f"Expected 2 dcat:DataService instances, found {len(services)}"


# --- Mandatory property tests ---

def test_catalog_mandatory_properties(catalog_graph):
    catalogs = list(catalog_graph.subjects(RDF.type, DCAT.Catalog))
    assert len(catalogs) == 1
    cat = catalogs[0]
    titles = list(catalog_graph.objects(cat, DCTERMS.title))
    assert len(titles) >= 1, "Catalog missing dct:title"
    descs = list(catalog_graph.objects(cat, DCTERMS.description))
    assert len(descs) >= 1, "Catalog missing dct:description"
    pubs = list(catalog_graph.objects(cat, DCTERMS.publisher))
    assert len(pubs) == 1, f"Catalog must have exactly 1 dct:publisher, found {len(pubs)}"


def test_catalog_links_all_datasets(catalog_graph):
    catalogs = list(catalog_graph.subjects(RDF.type, DCAT.Catalog))
    cat = catalogs[0]
    linked_datasets = set(catalog_graph.objects(cat, DCAT.dataset))
    all_datasets = set(catalog_graph.subjects(RDF.type, DCAT.Dataset))
    assert linked_datasets == all_datasets, (
        f"Catalog must link to all datasets. Missing: {all_datasets - linked_datasets}"
    )


def test_catalog_links_all_services(catalog_graph):
    catalogs = list(catalog_graph.subjects(RDF.type, DCAT.Catalog))
    cat = catalogs[0]
    linked_services = set(catalog_graph.objects(cat, DCAT.service))
    all_services = set(catalog_graph.subjects(RDF.type, DCAT.DataService))
    assert linked_services == all_services, (
        f"Catalog must link to all data services. Missing: {all_services - linked_services}"
    )


def test_all_datasets_have_title_and_description(catalog_graph):
    datasets = list(catalog_graph.subjects(RDF.type, DCAT.Dataset))
    for ds in datasets:
        titles = list(catalog_graph.objects(ds, DCTERMS.title))
        assert len(titles) >= 1, f"Dataset {ds} missing dct:title"
        descs = list(catalog_graph.objects(ds, DCTERMS.description))
        assert len(descs) >= 1, f"Dataset {ds} missing dct:description"


def test_all_distributions_have_access_url(catalog_graph):
    dists = list(catalog_graph.subjects(RDF.type, DCAT.Distribution))
    for dist in dists:
        access_urls = list(catalog_graph.objects(dist, DCAT.accessURL))
        assert len(access_urls) >= 1, f"Distribution {dist} missing dcat:accessURL"


def test_all_dataservices_have_endpoint_url(catalog_graph):
    services = list(catalog_graph.subjects(RDF.type, DCAT.DataService))
    for svc in services:
        endpoints = list(catalog_graph.objects(svc, DCAT.endpointURL))
        assert len(endpoints) >= 1, f"DataService {svc} missing dcat:endpointURL"


# --- Supporting class tests ---

def test_publisher_typing(catalog_graph):
    """All resources referenced via dct:publisher must be typed as foaf:Agent."""
    publishers = set()
    for s, p, o in catalog_graph.triples((None, DCTERMS.publisher, None)):
        publishers.add(o)
    assert len(publishers) >= 1, "No publishers found in the graph"
    for pub in publishers:
        types = set(catalog_graph.objects(pub, RDF.type))
        assert FOAF.Agent in types, f"Publisher {pub} is not typed as foaf:Agent"


def test_publisher_has_name(catalog_graph):
    """All foaf:Agent instances must have foaf:name (mandatory per SHACL shapes)."""
    agents = list(catalog_graph.subjects(RDF.type, FOAF.Agent))
    assert len(agents) >= 1, "No foaf:Agent found"
    for agent in agents:
        names = list(catalog_graph.objects(agent, FOAF.name))
        assert len(names) >= 1, f"Agent {agent} missing foaf:name"


def test_theme_typing(catalog_graph):
    """All resources referenced via dcat:theme must be typed as skos:Concept."""
    themes = set()
    for s, p, o in catalog_graph.triples((None, DCAT.theme, None)):
        themes.add(o)
    assert len(themes) >= 1, "No themes found"
    for theme in themes:
        types = set(catalog_graph.objects(theme, RDF.type))
        assert SKOS.Concept in types, f"Theme {theme} is not typed as skos:Concept"


def test_concept_has_preflabel(catalog_graph):
    """All skos:Concept instances must have skos:prefLabel (mandatory per SHACL shapes)."""
    concepts = list(catalog_graph.subjects(RDF.type, SKOS.Concept))
    assert len(concepts) >= 1, "No skos:Concept found"
    for concept in concepts:
        labels = list(catalog_graph.objects(concept, SKOS.prefLabel))
        assert len(labels) >= 1, f"Concept {concept} missing skos:prefLabel"


def test_concept_scheme_has_title(catalog_graph):
    """All skos:ConceptScheme instances must have dct:title (mandatory per SHACL shapes)."""
    schemes = list(catalog_graph.subjects(RDF.type, SKOS.ConceptScheme))
    for scheme in schemes:
        titles = list(catalog_graph.objects(scheme, DCTERMS.title))
        assert len(titles) >= 1, f"ConceptScheme {scheme} missing dct:title"


def test_language_typing(catalog_graph):
    """All resources referenced via dct:language must be typed as dct:LinguisticSystem."""
    languages = set()
    for s, p, o in catalog_graph.triples((None, DCTERMS.language, None)):
        languages.add(o)
    assert len(languages) >= 1, "No languages found"
    for lang in languages:
        types = set(catalog_graph.objects(lang, RDF.type))
        assert DCTERMS.LinguisticSystem in types, f"Language {lang} not typed as dct:LinguisticSystem"


def test_spatial_typing(catalog_graph):
    """All resources referenced via dct:spatial must be typed as dct:Location."""
    locations = set()
    for s, p, o in catalog_graph.triples((None, DCTERMS.spatial, None)):
        locations.add(o)
    assert len(locations) >= 1, "No spatial references found"
    for loc in locations:
        types = set(catalog_graph.objects(loc, RDF.type))
        assert DCTERMS.Location in types, f"Spatial {loc} not typed as dct:Location"


def test_dataservice_serves_datasets(catalog_graph):
    """Data services that declare serves_datasets must reference valid dcat:Dataset instances."""
    services = list(catalog_graph.subjects(RDF.type, DCAT.DataService))
    all_datasets = set(catalog_graph.subjects(RDF.type, DCAT.Dataset))
    for svc in services:
        served = set(catalog_graph.objects(svc, DCAT.servesDataset))
        for ds in served:
            assert ds in all_datasets, f"DataService {svc} serves {ds} which is not typed as dcat:Dataset"


def test_temporal_coverage_typing(catalog_graph):
    """All resources referenced via dct:temporal must be typed as dct:PeriodOfTime."""
    periods = set()
    for s, p, o in catalog_graph.triples((None, DCTERMS.temporal, None)):
        periods.add(o)
    for period in periods:
        types = set(catalog_graph.objects(period, RDF.type))
        assert DCTERMS.PeriodOfTime in types, f"Temporal {period} not typed as dct:PeriodOfTime"


# --- Additional class typing checks ---

def test_license_typing(catalog_graph):
    """All resources referenced via dct:license must be typed as dct:LicenseDocument."""
    licenses = set()
    for s, p, o in catalog_graph.triples((None, DCTERMS.license, None)):
        licenses.add(o)
    assert len(licenses) >= 1, "No licenses found"
    for lic in licenses:
        types = set(catalog_graph.objects(lic, RDF.type))
        assert DCTERMS.LicenseDocument in types, f"License {lic} not typed as dct:LicenseDocument"


def test_format_typing(catalog_graph):
    """All resources referenced via dct:format must be typed as dct:MediaTypeOrExtent."""
    formats = set()
    for s, p, o in catalog_graph.triples((None, DCTERMS.format, None)):
        formats.add(o)
    assert len(formats) >= 1, "No formats found"
    for fmt in formats:
        types = set(catalog_graph.objects(fmt, RDF.type))
        assert DCTERMS.MediaTypeOrExtent in types, f"Format {fmt} not typed as dct:MediaTypeOrExtent"


def test_frequency_typing(catalog_graph):
    """All resources referenced via dct:accrualPeriodicity must be typed as dct:Frequency."""
    freqs = set()
    for s, p, o in catalog_graph.triples((None, DCTERMS.accrualPeriodicity, None)):
        freqs.add(o)
    assert len(freqs) >= 1, "No frequencies found"
    for freq in freqs:
        types = set(catalog_graph.objects(freq, RDF.type))
        assert DCTERMS.Frequency in types, f"Frequency {freq} not typed as dct:Frequency"


def test_standard_typing(catalog_graph):
    """All resources referenced via dct:conformsTo must be typed as dct:Standard."""
    standards = set()
    for s, p, o in catalog_graph.triples((None, DCTERMS.conformsTo, None)):
        standards.add(o)
    assert len(standards) >= 1, "No standards found"
    for std in standards:
        types = set(catalog_graph.objects(std, RDF.type))
        assert DCTERMS.Standard in types, f"Standard {std} not typed as dct:Standard"
