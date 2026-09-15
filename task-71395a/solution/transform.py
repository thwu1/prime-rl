#!/usr/bin/env python3
"""Transform registry.json into a DCAT-AP 3.0.1 compliant Turtle catalog."""

import json
import os
import re
from datetime import datetime
from rdflib import Graph, Literal, Namespace, URIRef, BNode
from rdflib.namespace import RDF, XSD, DCTERMS, FOAF, SKOS, DCAT

# Additional namespaces
VCARD = Namespace("http://www.w3.org/2006/vcard/ns#")
ELI = Namespace("http://data.europa.eu/eli/ontology#")
R5R = Namespace("http://data.europa.eu/r5r/")

# EU Publications Office authority table base URIs
AUTH_THEME = "http://publications.europa.eu/resource/authority/data-theme/"
AUTH_LANG = "http://publications.europa.eu/resource/authority/language/"
AUTH_FREQ = "http://publications.europa.eu/resource/authority/frequency/"
AUTH_FILETYPE = "http://publications.europa.eu/resource/authority/file-type/"
AUTH_COUNTRY = "http://publications.europa.eu/resource/authority/country/"

# ISO 639-1 to EU authority language code mapping
LANG_MAP = {
    "en": "ENG", "fr": "FRA", "de": "DEU", "es": "SPA",
    "it": "ITA", "nl": "NLD", "pt": "POR", "pl": "POL",
    "cs": "CES", "da": "DAN", "el": "ELL", "fi": "FIN",
    "hu": "HUN", "ga": "GLE", "hr": "HRV", "lt": "LIT",
    "lv": "LAV", "mt": "MLT", "ro": "RON", "sk": "SLK",
    "sl": "SLV", "sv": "SWE", "bg": "BUL", "et": "EST",
}

# Language code to label mapping
LANG_LABELS = {
    "ENG": "English", "FRA": "French", "DEU": "German", "SPA": "Spanish",
    "ITA": "Italian", "NLD": "Dutch", "POR": "Portuguese",
}

# Theme code to prefLabel mapping
THEME_LABELS = {
    "ECON": "Economy and finance",
    "GOVE": "Government and public sector",
    "TECH": "Science and technology",
    "JUST": "Justice, legal system and public safety",
    "REGI": "Regions and cities",
    "EDUC": "Education, culture and sport",
    "ENER": "Energy",
    "ENVI": "Environment",
    "HEAL": "Health",
    "INTR": "International issues",
    "AGRI": "Agriculture, fisheries, forestry and food",
    "SOCI": "Population and society",
    "TRAN": "Transport",
}

# Format short name to EU file-type authority code mapping
FORMAT_MAP = {
    "CSV": "CSV", "JSON": "JSON", "JSONLD": "JSON_LD",
    "XML": "XML", "RDF_XML": "RDF_XML", "PDF": "PDF",
    "GEOJSON": "GEOJSON", "WMS": "WMS", "HTML": "HTML",
}

# License SPDX ID to URI mapping
LICENSE_MAP = {
    "CC-BY-4.0": "http://creativecommons.org/licenses/by/4.0/",
    "CC-BY-NC-4.0": "http://creativecommons.org/licenses/by-nc/4.0/",
    "CC0-1.0": "http://creativecommons.org/publicdomain/zero/1.0/",
}

BASE = "https://data.edia.europa.eu/"


def normalize_date(date_str):
    """Normalize various date formats to ISO 8601 (YYYY-MM-DD)."""
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return date_str
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", date_str)
    if m:
        return f"{m.group(3)}-{m.group(1)}-{m.group(2)}"
    for fmt in ["%B %d, %Y", "%B %d %Y"]:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    try:
        dt = datetime.strptime(date_str, "%B %Y")
        return dt.strftime("%Y-%m-01")
    except ValueError:
        pass
    return date_str


def main():
    with open("/app/registry.json") as f:
        registry = json.load(f)

    g = Graph()
    g.bind("dcat", DCAT)
    g.bind("dct", DCTERMS)
    g.bind("foaf", FOAF)
    g.bind("skos", SKOS)
    g.bind("vcard", VCARD)
    g.bind("xsd", XSD)
    g.bind("eli", ELI)
    g.bind("r5r", R5R)

    catalog_info = registry["catalog_info"]
    catalog_uri = URIRef(BASE + "catalog")

    # --- Catalog ---
    g.add((catalog_uri, RDF.type, DCAT.Catalog))
    g.add((catalog_uri, DCTERMS.title, Literal(catalog_info["title"], lang="en")))
    g.add((catalog_uri, DCTERMS.description, Literal(catalog_info["description"], lang="en")))

    # Catalog publisher (mandatory, maxCount 1)
    cat_pub_uri = URIRef(BASE + "organization/edia")
    g.add((catalog_uri, DCTERMS.publisher, cat_pub_uri))
    g.add((cat_pub_uri, RDF.type, FOAF.Agent))
    g.add((cat_pub_uri, FOAF.name, Literal(catalog_info["publisher"]["name"], lang="en")))

    # Catalog homepage
    homepage_uri = URIRef(catalog_info["homepage"])
    g.add((catalog_uri, FOAF.homepage, homepage_uri))
    g.add((homepage_uri, RDF.type, FOAF.Document))

    # Catalog languages
    for lang_code in catalog_info.get("language", []):
        auth_code = LANG_MAP.get(lang_code, lang_code.upper())
        lang_uri = URIRef(AUTH_LANG + auth_code)
        g.add((catalog_uri, DCTERMS.language, lang_uri))
        g.add((lang_uri, RDF.type, DCTERMS.LinguisticSystem))

    # Catalog spatial coverage
    for spatial_code in catalog_info.get("spatial_coverage", []):
        sp_code = "EUR" if spatial_code == "EU" else spatial_code
        spatial_uri = URIRef(AUTH_COUNTRY + sp_code)
        g.add((catalog_uri, DCTERMS.spatial, spatial_uri))
        g.add((spatial_uri, RDF.type, DCTERMS.Location))

    # Catalog theme taxonomy
    if "themes_taxonomy" in catalog_info:
        tax_uri = URIRef(catalog_info["themes_taxonomy"])
        g.add((catalog_uri, DCAT.themeTaxonomy, tax_uri))
        g.add((tax_uri, RDF.type, SKOS.ConceptScheme))
        g.add((tax_uri, DCTERMS.title, Literal("EU Data Themes", lang="en")))

    # Catalog license
    if "license" in catalog_info:
        lic_uri = URIRef(LICENSE_MAP.get(catalog_info["license"], catalog_info["license"]))
        g.add((catalog_uri, DCTERMS.license, lic_uri))
        g.add((lic_uri, RDF.type, DCTERMS.LicenseDocument))

    # Catalog dates
    if "issued" in catalog_info:
        g.add((catalog_uri, DCTERMS.issued, Literal(normalize_date(catalog_info["issued"]), datatype=XSD.date)))
    if "modified" in catalog_info:
        g.add((catalog_uri, DCTERMS.modified, Literal(normalize_date(catalog_info["modified"]), datatype=XSD.date)))

    # Caches
    publisher_cache = {}
    theme_cache = set()
    license_cache = set()

    def get_publisher_uri(name):
        if name not in publisher_cache:
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            uri = URIRef(BASE + "organization/" + slug)
            g.add((uri, RDF.type, FOAF.Agent))
            g.add((uri, FOAF.name, Literal(name, lang="en")))
            publisher_cache[name] = uri
        return publisher_cache[name]

    def add_contact_point(subject, contact_info):
        cp = BNode()
        g.add((cp, RDF.type, VCARD.Kind))
        g.add((subject, DCAT.contactPoint, cp))
        if "name" in contact_info:
            g.add((cp, VCARD.fn, Literal(contact_info["name"])))
        if "email" in contact_info:
            g.add((cp, VCARD.hasEmail, URIRef("mailto:" + contact_info["email"])))
        if "phone" in contact_info:
            g.add((cp, VCARD.hasTelephone, URIRef("tel:" + contact_info["phone"])))

    def add_themes(subject, theme_codes):
        for code in theme_codes:
            theme_uri = URIRef(AUTH_THEME + code)
            g.add((subject, DCAT.theme, theme_uri))
            if code not in theme_cache:
                g.add((theme_uri, RDF.type, SKOS.Concept))
                label = THEME_LABELS.get(code, code)
                g.add((theme_uri, SKOS.prefLabel, Literal(label, lang="en")))
                theme_cache.add(code)

    def add_license(license_id):
        lic_uri = URIRef(LICENSE_MAP.get(license_id, license_id))
        if license_id not in license_cache:
            g.add((lic_uri, RDF.type, DCTERMS.LicenseDocument))
            license_cache.add(license_id)
        return lic_uri

    # --- Datasets ---
    dataset_uris = {}
    for ds in registry.get("datasets", []):
        ds_id = ds["id"]
        ds_uri = URIRef(BASE + "dataset/" + ds_id)
        dataset_uris[ds_id] = ds_uri

        g.add((ds_uri, RDF.type, DCAT.Dataset))
        g.add((catalog_uri, DCAT.dataset, ds_uri))
        g.add((ds_uri, DCTERMS.title, Literal(ds["title"], lang="en")))
        g.add((ds_uri, DCTERMS.description, Literal(ds["description"], lang="en")))

        # Publisher
        if "publisher_name" in ds:
            pub = get_publisher_uri(ds["publisher_name"])
            g.add((ds_uri, DCTERMS.publisher, pub))

        # Contact point
        if "contact" in ds:
            add_contact_point(ds_uri, ds["contact"])

        # Themes
        add_themes(ds_uri, ds.get("themes", []))

        # Keywords
        for kw in ds.get("keywords", []):
            g.add((ds_uri, DCAT.keyword, Literal(kw, lang="en")))

        # Temporal coverage
        if "temporal" in ds:
            temp = BNode()
            g.add((temp, RDF.type, DCTERMS.PeriodOfTime))
            g.add((ds_uri, DCTERMS.temporal, temp))
            if "start" in ds["temporal"]:
                g.add((temp, DCAT.startDate, Literal(normalize_date(ds["temporal"]["start"]), datatype=XSD.date)))
            if "end" in ds["temporal"]:
                g.add((temp, DCAT.endDate, Literal(normalize_date(ds["temporal"]["end"]), datatype=XSD.date)))

        # Spatial coverage
        if "spatial" in ds:
            sp_code = "EUR" if ds["spatial"] == "EU" else ds["spatial"]
            sp_uri = URIRef(AUTH_COUNTRY + sp_code)
            g.add((ds_uri, DCTERMS.spatial, sp_uri))
            g.add((sp_uri, RDF.type, DCTERMS.Location))

        # Frequency
        if "frequency" in ds:
            freq_uri = URIRef(AUTH_FREQ + ds["frequency"])
            g.add((ds_uri, DCTERMS.accrualPeriodicity, freq_uri))
            g.add((freq_uri, RDF.type, DCTERMS.Frequency))

        # Language
        for lang_code in ds.get("language", []):
            auth_code = LANG_MAP.get(lang_code, lang_code.upper())
            lang_uri = URIRef(AUTH_LANG + auth_code)
            g.add((ds_uri, DCTERMS.language, lang_uri))
            g.add((lang_uri, RDF.type, DCTERMS.LinguisticSystem))

        # Landing page
        if "landing_page" in ds:
            lp_uri = URIRef(ds["landing_page"])
            g.add((ds_uri, DCAT.landingPage, lp_uri))
            g.add((lp_uri, RDF.type, FOAF.Document))

        # Conforms to
        if "conforms_to" in ds:
            std_uri = URIRef(ds["conforms_to"])
            g.add((ds_uri, DCTERMS.conformsTo, std_uri))
            g.add((std_uri, RDF.type, DCTERMS.Standard))

        # Applicable legislation
        if "applicable_legislation" in ds:
            leg_uri = URIRef(ds["applicable_legislation"])
            g.add((ds_uri, R5R.applicableLegislation, leg_uri))
            g.add((leg_uri, RDF.type, ELI.LegalResource))

        # Access rights
        if "access_rights" in ds:
            ar_uri = URIRef("http://publications.europa.eu/resource/authority/access-right/" + ds["access_rights"])
            g.add((ds_uri, DCTERMS.accessRights, ar_uri))
            g.add((ar_uri, RDF.type, DCTERMS.RightsStatement))

        # Issued date
        if "issued" in ds:
            g.add((ds_uri, DCTERMS.issued, Literal(normalize_date(ds["issued"]), datatype=XSD.date)))

        # Distributions
        for i, dist in enumerate(ds.get("distributions", [])):
            dist_uri = URIRef(BASE + "distribution/" + ds_id + "-" + str(i + 1))
            g.add((dist_uri, RDF.type, DCAT.Distribution))
            g.add((ds_uri, DCAT.distribution, dist_uri))

            if "title" in dist:
                g.add((dist_uri, DCTERMS.title, Literal(dist["title"], lang="en")))
            if "description" in dist:
                g.add((dist_uri, DCTERMS.description, Literal(dist["description"], lang="en")))

            # accessURL (mandatory)
            g.add((dist_uri, DCAT.accessURL, URIRef(dist["access_url"])))

            if "download_url" in dist:
                g.add((dist_uri, DCAT.downloadURL, URIRef(dist["download_url"])))

            # Format
            if "format" in dist:
                fmt_code = FORMAT_MAP.get(dist["format"], dist["format"])
                fmt_uri = URIRef(AUTH_FILETYPE + fmt_code)
                g.add((dist_uri, DCTERMS.format, fmt_uri))
                g.add((fmt_uri, RDF.type, DCTERMS.MediaTypeOrExtent))

            # Media type
            if "media_type" in dist:
                mt_uri = URIRef("https://www.iana.org/assignments/media-types/" + dist["media_type"])
                g.add((dist_uri, DCAT.mediaType, mt_uri))
                g.add((mt_uri, RDF.type, DCTERMS.MediaType))

            # Byte size
            if "byte_size" in dist:
                g.add((dist_uri, DCAT.byteSize, Literal(dist["byte_size"], datatype=XSD.nonNegativeInteger)))

            # License
            if "license" in dist:
                lic_uri = add_license(dist["license"])
                g.add((dist_uri, DCTERMS.license, lic_uri))

            # Issued
            if "issued" in dist:
                g.add((dist_uri, DCTERMS.issued, Literal(normalize_date(dist["issued"]), datatype=XSD.date)))

    # --- Data Services ---
    for svc in registry.get("data_services", []):
        svc_id = svc["id"]
        svc_uri = URIRef(BASE + "service/" + svc_id)

        g.add((svc_uri, RDF.type, DCAT.DataService))
        g.add((catalog_uri, DCAT.service, svc_uri))

        g.add((svc_uri, DCTERMS.title, Literal(svc["title"], lang="en")))
        if "description" in svc:
            g.add((svc_uri, DCTERMS.description, Literal(svc["description"], lang="en")))

        # endpointURL (mandatory)
        g.add((svc_uri, DCAT.endpointURL, URIRef(svc["endpoint_url"])))

        if "endpoint_description" in svc:
            g.add((svc_uri, DCAT.endpointDescription, URIRef(svc["endpoint_description"])))

        # Serves datasets
        for ds_id in svc.get("serves_datasets", []):
            if ds_id in dataset_uris:
                g.add((svc_uri, DCAT.servesDataset, dataset_uris[ds_id]))

        # Publisher
        if "publisher_name" in svc:
            pub = get_publisher_uri(svc["publisher_name"])
            g.add((svc_uri, DCTERMS.publisher, pub))

        # Contact point
        if "contact" in svc:
            add_contact_point(svc_uri, svc["contact"])

        # Conforms to
        if "conforms_to" in svc:
            std_uri = URIRef(svc["conforms_to"])
            g.add((svc_uri, DCTERMS.conformsTo, std_uri))
            g.add((std_uri, RDF.type, DCTERMS.Standard))

        # License
        if "license" in svc:
            lic_uri = add_license(svc["license"])
            g.add((svc_uri, DCTERMS.license, lic_uri))

        # Themes
        add_themes(svc_uri, svc.get("themes", []))

    # --- Serialize ---
    os.makedirs("/app/output", exist_ok=True)
    g.serialize("/app/output/catalog.ttl", format="turtle")
    print(f"Catalog written to /app/output/catalog.ttl with {len(g)} triples")


if __name__ == "__main__":
    main()
