#!/usr/bin/env python3
"""Fix the broken DCAT-AP 3.0.1 catalog, produce audit report, shapes, and validate script."""

import json
import os
from rdflib import Graph, Namespace, URIRef, Literal, BNode, RDF, XSD
from rdflib.namespace import DCTERMS, FOAF

DCAT = Namespace("http://www.w3.org/ns/dcat#")
VCARD = Namespace("http://www.w3.org/2006/vcard/ns#")
SH = Namespace("http://www.w3.org/ns/shacl#")

BASE = "http://env-data.europa.eu/"


def fix_catalog():
    g = Graph()
    g.parse("/app/broken_catalog.ttl", format="turtle")

    with open("/app/manifest.json") as f:
        manifest = json.load(f)

    audit = []
    error_num = 1

    def add_error(cat, entity, desc, fix):
        nonlocal error_num
        audit.append({
            "error_id": f"E{error_num:03d}",
            "category": cat,
            "entity": entity,
            "description": desc,
            "fix": fix
        })
        error_num += 1

    # --- Error 1: Fix publisher types (foaf:Organization -> foaf:Agent) ---
    for pub in list(g.subjects(RDF.type, FOAF.Organization)):
        g.remove((pub, RDF.type, FOAF.Organization))
        g.add((pub, RDF.type, FOAF.Agent))
        add_error("structural_modeling", str(pub),
                  "Publisher typed as foaf:Organization instead of foaf:Agent",
                  "Changed type to foaf:Agent as required by DCAT-AP 3.0.1")

    # --- Error 2: Fix dct:format literal on DIST001 ---
    for s, p, o in list(g.triples((None, DCTERMS.format, None))):
        if isinstance(o, Literal):
            g.remove((s, p, o))
            g.add((s, DCTERMS.format, URIRef(
                "http://publications.europa.eu/resource/authority/file-type/CSV")))
            add_error("property_usage", str(s),
                      f"dct:format is a literal string '{o}' instead of EU file-type URI",
                      "Changed to EU authority file-type URI")

    # --- Error 3: Fix contactPoint literal on DS001 ---
    ds001 = URIRef(BASE + "dataset/DS001")
    ds001_contact = manifest["entities"]["datasets"]["DS001"]["contact"]
    for cp in list(g.objects(ds001, DCAT.contactPoint)):
        if isinstance(cp, Literal):
            g.remove((ds001, DCAT.contactPoint, cp))
            cp_node = BNode()
            g.add((cp_node, RDF.type, VCARD.Kind))
            g.add((cp_node, VCARD.fn, Literal(ds001_contact["name"])))
            g.add((cp_node, VCARD.hasEmail, URIRef("mailto:" + ds001_contact["email"])))
            g.add((ds001, DCAT.contactPoint, cp_node))
            add_error("structural_modeling", str(ds001),
                      "dcat:contactPoint is a literal string instead of vcard:Kind node",
                      "Created vcard:Kind blank node with fn and hasEmail from manifest")

    # --- Error 4: Fix temporal bare date on DS002 ---
    ds002 = URIRef(BASE + "dataset/DS002")
    ds002_temporal = manifest["entities"]["datasets"]["DS002"]["temporal"]
    for temp in list(g.objects(ds002, DCTERMS.temporal)):
        if isinstance(temp, Literal):
            g.remove((ds002, DCTERMS.temporal, temp))
            period = BNode()
            g.add((period, RDF.type, DCTERMS.PeriodOfTime))
            g.add((period, DCAT.startDate,
                   Literal(ds002_temporal["start"], datatype=XSD.date)))
            g.add((period, DCAT.endDate,
                   Literal(ds002_temporal["end"], datatype=XSD.date)))
            g.add((ds002, DCTERMS.temporal, period))
            add_error("structural_modeling", str(ds002),
                      "dct:temporal is a bare date literal instead of dct:PeriodOfTime node",
                      "Created PeriodOfTime node with startDate and endDate")

    # --- Error 5: Fix theme URIs (wrong prefix) ---
    wrong_theme_prefix = "http://data.europa.eu/resource/authority/data-theme/"
    correct_theme_prefix = "http://publications.europa.eu/resource/authority/data-theme/"
    for s, p, o in list(g.triples((None, DCAT.theme, None))):
        if isinstance(o, URIRef) and str(o).startswith(wrong_theme_prefix):
            code = str(o).replace(wrong_theme_prefix, "")
            g.remove((s, p, o))
            g.add((s, DCAT.theme, URIRef(correct_theme_prefix + code)))
            add_error("vocabulary_alignment", str(s),
                      f"Theme URI uses data.europa.eu prefix instead of publications.europa.eu",
                      f"Changed to {correct_theme_prefix + code}")

    # --- Error 6: Fix language literals on catalog ---
    cat = URIRef(BASE + "catalog")
    lang_map = {"en": "ENG", "fr": "FRA", "de": "DEU"}
    for lang in list(g.objects(cat, DCTERMS.language)):
        if isinstance(lang, Literal):
            code = lang_map.get(str(lang), str(lang).upper())
            g.remove((cat, DCTERMS.language, lang))
            g.add((cat, DCTERMS.language, URIRef(
                f"http://publications.europa.eu/resource/authority/language/{code}")))
            add_error("vocabulary_alignment", str(cat),
                      f"dct:language is a literal '{lang}' instead of authority table URI",
                      f"Changed to language authority URI for {code}")

    # --- Error 7: Fix Dublin Core frequency on DS002 ---
    dc_freq_prefix = "http://purl.org/cld/freq/"
    eu_freq_map = {
        "quarterly": "QUARTERLY", "annual": "ANNUAL",
        "monthly": "MONTHLY", "hourly": "HOURLY"
    }
    for s, p, o in list(g.triples((None, DCTERMS.accrualPeriodicity, None))):
        if isinstance(o, URIRef) and str(o).startswith(dc_freq_prefix):
            code = str(o).replace(dc_freq_prefix, "")
            eu_code = eu_freq_map.get(code, code.upper())
            g.remove((s, p, o))
            g.add((s, DCTERMS.accrualPeriodicity, URIRef(
                f"http://publications.europa.eu/resource/authority/frequency/{eu_code}")))
            add_error("vocabulary_alignment", str(s),
                      f"Frequency uses Dublin Core URI instead of EU authority table",
                      f"Changed to EU frequency authority URI ({eu_code})")

    # --- Error 8: Fix SPDX license URI ---
    spdx_uri = URIRef("https://spdx.org/licenses/CC-BY-4.0")
    eu_license = URIRef(
        "http://publications.europa.eu/resource/authority/licence/CC_BY_4_0")
    for s, p, o in list(g.triples((None, DCTERMS.license, spdx_uri))):
        g.remove((s, p, o))
        g.add((s, DCTERMS.license, eu_license))
        add_error("vocabulary_alignment", str(s),
                  "License uses SPDX URI instead of EU authority licence URI",
                  "Changed to EU authority licence/CC_BY_4_0")

    # --- Error 9: Fix accessURL as literal ---
    for s, p, o in list(g.triples((None, DCAT.accessURL, None))):
        if isinstance(o, Literal):
            g.remove((s, p, o))
            g.add((s, DCAT.accessURL, URIRef(str(o))))
            add_error("property_usage", str(s),
                      "dcat:accessURL is a literal string instead of an IRI",
                      "Changed to IRI")

    # --- Error 10: Fix byteSize datatype ---
    for s, p, o in list(g.triples((None, DCAT.byteSize, None))):
        if isinstance(o, Literal) and o.datatype == XSD.integer:
            g.remove((s, p, o))
            g.add((s, DCAT.byteSize,
                   Literal(str(o), datatype=XSD.nonNegativeInteger)))
            add_error("literal_correctness", str(s),
                      "dcat:byteSize has datatype xsd:integer instead of xsd:nonNegativeInteger",
                      "Changed datatype to xsd:nonNegativeInteger")

    # --- Error 11: Fix endpointUrl -> endpointURL ---
    wrong_prop = URIRef("http://www.w3.org/ns/dcat#endpointUrl")
    correct_prop = URIRef("http://www.w3.org/ns/dcat#endpointURL")
    for s, p, o in list(g.triples((None, wrong_prop, None))):
        g.remove((s, p, o))
        g.add((s, correct_prop, o))
        add_error("property_usage", str(s),
                  "Uses dcat:endpointUrl (lowercase u) instead of dcat:endpointURL",
                  "Changed to dcat:endpointURL (uppercase URL)")

    # --- Error 12: Add missing link to DS005 ---
    ds005 = URIRef(BASE + "dataset/DS005")
    if (cat, DCAT.dataset, ds005) not in g:
        g.add((cat, DCAT.dataset, ds005))
        add_error("cross_entity", str(cat),
                  "Catalog missing dcat:dataset link to DS005",
                  "Added dcat:dataset link to DS005")

    # --- Error 13: Fix DatasetSeries typing ---
    series = URIRef(BASE + "series/aq-monitoring")
    if (series, RDF.type, DCAT.DatasetSeries) not in g:
        # In DCAT-AP 3.0.1, DatasetSeries is NOT a subclass of Dataset
        g.remove((series, RDF.type, DCAT.Dataset))
        g.add((series, RDF.type, DCAT.DatasetSeries))
        add_error("structural_modeling", str(series),
                  "Dataset series incorrectly typed as dcat:Dataset instead of dcat:DatasetSeries",
                  "Changed type from dcat:Dataset to dcat:DatasetSeries")

    # --- Error 14: Fix title missing language tag ---
    ds003 = URIRef(BASE + "dataset/DS003")
    for title in list(g.objects(ds003, DCTERMS.title)):
        if isinstance(title, Literal) and title.language is None:
            g.remove((ds003, DCTERMS.title, title))
            g.add((ds003, DCTERMS.title, Literal(str(title), lang="en")))
            add_error("literal_correctness", str(ds003),
                      "dct:title missing language tag",
                      "Added @en language tag")

    # Bind prefixes and serialize
    g.bind("dcat", DCAT)
    g.bind("dct", DCTERMS)
    g.bind("foaf", FOAF)
    g.bind("vcard", VCARD)
    g.bind("xsd", XSD)
    g.serialize(destination="/app/catalog_fixed.ttl", format="turtle")

    with open("/app/audit_report.json", "w") as f:
        json.dump(audit, f, indent=2)

    print(f"Fixed {len(audit)} errors.")
    print(f"  catalog_fixed.ttl: {len(g)} triples")
    print(f"  audit_report.json: {len(audit)} entries")


def build_advanced_shapes():
    """Build 5 SHACL NodeShapes for cross-entity business rules."""
    shapes_ttl = (
        "@prefix sh: <http://www.w3.org/ns/shacl#> .\n"
        "@prefix dcat: <http://www.w3.org/ns/dcat#> .\n"
        "@prefix dct: <http://purl.org/dc/terms/> .\n"
        "@prefix vcard: <http://www.w3.org/2006/vcard/ns#> .\n"
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n"
        "@prefix ex: <http://env-data.europa.eu/shapes/> .\n\n"
        "# Prefix declarations for SPARQL constraints\n"
        'ex:PrefixDeclarations\n'
        '    sh:declare [\n'
        '        sh:prefix "dcat" ;\n'
        '        sh:namespace "http://www.w3.org/ns/dcat#"^^xsd:anyURI\n'
        '    ] , [\n'
        '        sh:prefix "dct" ;\n'
        '        sh:namespace "http://purl.org/dc/terms/"^^xsd:anyURI\n'
        '    ] , [\n'
        '        sh:prefix "vcard" ;\n'
        '        sh:namespace "http://www.w3.org/2006/vcard/ns#"^^xsd:anyURI\n'
        '    ] .\n\n'
        "# Shape 1: Dataset ContactPoint Completeness\n"
        "ex:DatasetContactPointShape a sh:NodeShape ;\n"
        "    sh:targetClass dcat:Dataset ;\n"
        "    sh:property [\n"
        "        sh:path dcat:contactPoint ;\n"
        "        sh:minCount 1 ;\n"
        "        sh:node ex:ContactPointDetailShape ;\n"
        '        sh:message "Every dataset must have a contactPoint with vcard:fn and vcard:hasEmail." ;\n'
        "    ] .\n\n"
        "ex:ContactPointDetailShape a sh:NodeShape ;\n"
        "    sh:property [\n"
        "        sh:path vcard:fn ;\n"
        "        sh:minCount 1 ;\n"
        '        sh:message "Contact point must have vcard:fn." ;\n'
        "    ] ;\n"
        "    sh:property [\n"
        "        sh:path vcard:hasEmail ;\n"
        "        sh:minCount 1 ;\n"
        '        sh:message "Contact point must have vcard:hasEmail." ;\n'
        "    ] .\n\n"
        "# Shape 2: CSV Distribution ByteSize Requirement\n"
        "ex:CsvByteSizeShape a sh:NodeShape ;\n"
        "    sh:targetClass dcat:Distribution ;\n"
        "    sh:sparql [\n"
        "        sh:prefixes ex:PrefixDeclarations ;\n"
        "        sh:select '''PREFIX dct: <http://purl.org/dc/terms/>\n"
        "PREFIX dcat: <http://www.w3.org/ns/dcat#>\n"
        "SELECT $this WHERE {\n"
        "    $this dct:format <http://publications.europa.eu/resource/authority/file-type/CSV> .\n"
        "    FILTER NOT EXISTS { $this dcat:byteSize ?size }\n"
        "}''' ;\n"
        '        sh:message "CSV distributions must specify dcat:byteSize." ;\n'
        "    ] .\n\n"
        "# Shape 3: Series Temporal Completeness\n"
        "ex:SeriesTemporalShape a sh:NodeShape ;\n"
        "    sh:targetClass dcat:Dataset ;\n"
        "    sh:sparql [\n"
        "        sh:prefixes ex:PrefixDeclarations ;\n"
        "        sh:select '''PREFIX dct: <http://purl.org/dc/terms/>\n"
        "PREFIX dcat: <http://www.w3.org/ns/dcat#>\n"
        "SELECT $this WHERE {\n"
        "    $this dcat:inSeries ?series .\n"
        "    OPTIONAL {\n"
        "        $this dct:temporal ?period .\n"
        "        ?period dcat:startDate ?start .\n"
        "        ?period dcat:endDate ?end .\n"
        "    }\n"
        "    FILTER(!bound(?start) || !bound(?end))\n"
        "}''' ;\n"
        '        sh:message "Datasets in a series must have temporal coverage with both startDate and endDate." ;\n'
        "    ] .\n\n"
        "# Shape 4: Distribution Referential Integrity\n"
        "ex:DistributionOrphanShape a sh:NodeShape ;\n"
        "    sh:targetClass dcat:Distribution ;\n"
        "    sh:sparql [\n"
        "        sh:prefixes ex:PrefixDeclarations ;\n"
        "        sh:select '''PREFIX dcat: <http://www.w3.org/ns/dcat#>\n"
        "SELECT $this WHERE {\n"
        "    $this a dcat:Distribution .\n"
        "    FILTER NOT EXISTS { ?ds dcat:distribution $this }\n"
        "}''' ;\n"
        '        sh:message "Every distribution must be referenced by at least one dataset via dcat:distribution." ;\n'
        "    ] .\n\n"
        "# Shape 5: CSV Distribution MediaType Requirement\n"
        "ex:CsvMediaTypeShape a sh:NodeShape ;\n"
        "    sh:targetClass dcat:Distribution ;\n"
        "    sh:sparql [\n"
        "        sh:prefixes ex:PrefixDeclarations ;\n"
        "        sh:select '''PREFIX dct: <http://purl.org/dc/terms/>\n"
        "PREFIX dcat: <http://www.w3.org/ns/dcat#>\n"
        "SELECT $this WHERE {\n"
        "    $this dct:format <http://publications.europa.eu/resource/authority/file-type/CSV> .\n"
        "    FILTER NOT EXISTS { $this dcat:mediaType ?mt }\n"
        "}''' ;\n"
        '        sh:message "CSV distributions must have a dcat:mediaType." ;\n'
        "    ] .\n"
    )
    with open("/app/advanced_shapes.ttl", "w") as f:
        f.write(shapes_ttl)
    print("  advanced_shapes.ttl written")


def build_validate_script():
    """Write an executable validation script."""
    script = (
        "#!/bin/bash\n"
        "# Validate catalog against advanced SHACL shapes\n"
        "pip3 install rdflib==7.1.4 pyshacl==0.26.0 -q 2>/dev/null\n\n"
        "python3 << 'PYEOF'\n"
        "from rdflib import Graph\n"
        "from pyshacl import validate\n\n"
        "data = Graph()\n"
        "data.parse('/app/catalog_fixed.ttl', format='turtle')\n"
        "print(f'Loaded {len(data)} triples from catalog_fixed.ttl')\n\n"
        "shapes = Graph()\n"
        "shapes.parse('/app/advanced_shapes.ttl', format='turtle')\n\n"
        "conforms, _, report = validate(data, shacl_graph=shapes, inference='none')\n"
        "print(report)\n"
        "if conforms:\n"
        "    print('RESULT: PASS - Catalog conforms to all advanced shapes.')\n"
        "else:\n"
        "    print('RESULT: FAIL - Catalog violates one or more advanced shapes.')\n"
        "    exit(1)\n"
        "PYEOF\n"
    )
    with open("/app/validate.sh", "w") as f:
        f.write(script)
    os.chmod("/app/validate.sh", 0o755)
    print("  validate.sh written and made executable")


if __name__ == "__main__":
    fix_catalog()
    build_advanced_shapes()
    build_validate_script()
    print("All artifacts generated successfully.")
