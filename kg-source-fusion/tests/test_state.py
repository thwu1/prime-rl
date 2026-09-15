
import json
import os
from rdflib import Graph, URIRef, Literal, RDF, RDFS

ONTO = "http://kg.org/ontology/"
SEED = "http://seed.kg/entity/"
TMDB = "http://tmdb.source/entity/"
JSON_NS = "http://json.source/entity/"
CSV_NS = "http://csv.source/entity/"


def load_fused_graph():
    g = Graph()
    g.parse("/app/output/fused.nt", format="nt")
    return g


def test_fused_kg_exists():
    assert os.path.exists("/app/output/fused.nt"), "Fused KG file not found at /app/output/fused.nt"


def test_match_clusters_exists():
    assert os.path.exists("/app/output/match_clusters.json"), "Match clusters file not found"


def test_entity_count():
    """Fused KG should have exactly 14 unique entities (subjects)."""
    g = load_fused_graph()
    entities = set(str(s) for s in g.subjects())
    assert len(entities) == 14, f"Expected 14 entities, got {len(entities)}: {sorted(entities)}"


def test_triple_count():
    """Fused KG should have exactly 78 triples."""
    g = load_fused_graph()
    assert len(g) == 78, f"Expected 78 triples, got {len(g)}"


def test_godfather_budget_conflict_resolution():
    """Budget of The Godfather must reflect the most reliable source."""
    g = load_fused_graph()
    budgets = list(g.objects(URIRef(SEED + "m1"), URIRef(ONTO + "budget")))
    assert len(budgets) == 1, f"Expected exactly 1 budget value, got {len(budgets)}: {budgets}"
    assert str(budgets[0]) == "6000000", f"Expected '6000000', got '{budgets[0]}'"


def test_godfather_gross_conflict_resolution():
    """Gross of The Godfather must reflect the most reliable source."""
    g = load_fused_graph()
    gross_vals = list(g.objects(URIRef(SEED + "m1"), URIRef(ONTO + "gross")))
    assert len(gross_vals) == 1, f"Expected 1 gross value, got {len(gross_vals)}"
    assert str(gross_vals[0]) == "245066411", f"Expected '245066411', got '{gross_vals[0]}'"


def test_pulp_fiction_budget_conflict_resolution():
    """Budget of Pulp Fiction must reflect the most reliable source."""
    g = load_fused_graph()
    budgets = list(g.objects(URIRef(SEED + "m2"), URIRef(ONTO + "budget")))
    assert len(budgets) == 1, f"Expected 1 budget, got {len(budgets)}"
    assert str(budgets[0]) == "8000000", f"Expected '8000000', got '{budgets[0]}'"


def test_entity_resolution_director_reservoir_dogs():
    """Reservoir Dogs must have a director that resolves to the correct canonical entity."""
    g = load_fused_graph()
    directors = list(g.objects(URIRef(JSON_NS + "json_m3"), URIRef(ONTO + "director")))
    assert len(directors) == 1, f"Expected 1 director for Reservoir Dogs, got {len(directors)}"
    assert str(directors[0]) == SEED + "p2", \
        f"Expected director to resolve to '{SEED}p2', got '{directors[0]}'"


def test_entity_resolution_starring_godfather():
    """The Godfather should include Marlon Brando as a starring actor."""
    g = load_fused_graph()
    starring = [str(o) for o in g.objects(URIRef(SEED + "m1"), URIRef(ONTO + "starring"))]
    assert TMDB + "pb" in starring, f"Expected '{TMDB}pb' in starring, got: {starring}"


def test_entity_resolution_production_pulp_fiction():
    """Pulp Fiction should include Miramax Films as production company."""
    g = load_fused_graph()
    prods = [str(o) for o in g.objects(URIRef(SEED + "m2"), URIRef(ONTO + "production"))]
    assert JSON_NS + "json_c1" in prods, f"Expected Miramax in production: {prods}"


def test_coppola_birthdate():
    """Coppola's birth date should be correctly resolved."""
    g = load_fused_graph()
    dates = list(g.objects(URIRef(SEED + "p1"), URIRef(ONTO + "birthDate")))
    assert len(dates) == 1, f"Expected 1 birthDate for Coppola, got {len(dates)}"
    assert str(dates[0]) == "1939-04-07"


def test_nolan_birthplace():
    """Nolan's birth place should be present."""
    g = load_fused_graph()
    places = [str(o) for o in g.objects(URIRef(TMDB + "pn"), URIRef(ONTO + "birthPlace"))]
    assert "London" in places, f"Expected 'London' in birthPlace, got: {places}"


def test_inception_exists():
    """Inception should be in the fused KG as a Film."""
    g = load_fused_graph()
    types = list(g.objects(URIRef(TMDB + "f3"), RDF.type))
    assert URIRef(ONTO + "Film") in types, f"Inception not found or wrong type: {types}"


def test_warner_bros_type_mapping():
    """Warner Bros. should be typed as Company in the target ontology."""
    g = load_fused_graph()
    types = list(g.objects(URIRef(TMDB + "cw"), RDF.type))
    assert URIRef(ONTO + "Company") in types, f"Expected Company type for Warner Bros., got {types}"


def test_al_pacino_exists():
    """Al Pacino should be in the fused KG as a Person."""
    g = load_fused_graph()
    types = list(g.objects(URIRef(CSV_NS + "csv_p4"), RDF.type))
    assert URIRef(ONTO + "Person") in types, f"Al Pacino not found or wrong type: {types}"


def test_al_pacino_properties():
    """Al Pacino should have all expected properties."""
    g = load_fused_graph()
    bp = [str(o) for o in g.objects(URIRef(CSV_NS + "csv_p4"), URIRef(ONTO + "birthPlace"))]
    assert "New York City" in bp
    occ = [str(o) for o in g.objects(URIRef(CSV_NS + "csv_p4"), URIRef(ONTO + "occupation"))]
    assert "Actor" in occ


def test_no_duplicate_entities_json_m1():
    """json_m1 must be merged into its canonical entity, not appear as a separate subject."""
    g = load_fused_graph()
    triples = list(g.triples((URIRef(JSON_NS + "json_m1"), None, None)))
    assert len(triples) == 0, \
        f"json_m1 should be merged, but found {len(triples)} triples with json_m1 as subject"


def test_no_duplicate_entities_csv_p1():
    """csv_p1 must be merged into its canonical entity, not appear as a separate subject."""
    g = load_fused_graph()
    triples = list(g.triples((URIRef(CSV_NS + "csv_p1"), None, None)))
    assert len(triples) == 0, \
        f"csv_p1 should be merged, but found {len(triples)} triples"


def test_no_duplicate_entities_tmdb_f1():
    """tmdb:f1 must be merged into its canonical entity, not appear as a separate subject."""
    g = load_fused_graph()
    triples = list(g.triples((URIRef(TMDB + "f1"), None, None)))
    assert len(triples) == 0, \
        f"tmdb:f1 should be merged, but found {len(triples)} triples"


def test_genres_preserved():
    """Non-functional properties should preserve all distinct values."""
    g = load_fused_graph()
    genres = sorted([str(o) for o in g.objects(URIRef(SEED + "m1"), URIRef(ONTO + "genre"))])
    assert genres == ["Crime", "Drama"], f"Expected ['Crime', 'Drama'], got {genres}"


def test_match_clusters_godfather():
    """The Godfather match cluster must contain all source representations."""
    with open("/app/output/match_clusters.json") as f:
        data = json.load(f)
    clusters = data["clusters"]

    godfather_cluster = None
    for c in clusters:
        if SEED + "m1" in c["members"]:
            godfather_cluster = c
            break

    assert godfather_cluster is not None, "Godfather match cluster not found"
    assert godfather_cluster["canonical"] == SEED + "m1", \
        f"Wrong canonical for Godfather: {godfather_cluster['canonical']}"
    assert TMDB + "f1" in godfather_cluster["members"], "tmdb:f1 not in Godfather cluster"
    assert JSON_NS + "json_m1" in godfather_cluster["members"], "json:json_m1 not in Godfather cluster"


def test_match_clusters_coppola():
    """Coppola should be matched across multiple sources."""
    with open("/app/output/match_clusters.json") as f:
        data = json.load(f)
    clusters = data["clusters"]

    coppola_cluster = None
    for c in clusters:
        if SEED + "p1" in c["members"]:
            coppola_cluster = c
            break

    assert coppola_cluster is not None, "Coppola cluster not found"
    assert coppola_cluster["canonical"] == SEED + "p1"
    assert JSON_NS + "json_p1" in coppola_cluster["members"]
    assert CSV_NS + "csv_p1" in coppola_cluster["members"]


def test_match_clusters_brando():
    """Brando should be matched between sources with correct canonical selection."""
    with open("/app/output/match_clusters.json") as f:
        data = json.load(f)
    clusters = data["clusters"]

    brando_cluster = None
    for c in clusters:
        if TMDB + "pb" in c["members"]:
            brando_cluster = c
            break

    assert brando_cluster is not None, "Brando cluster not found"
    assert brando_cluster["canonical"] == TMDB + "pb", \
        f"Expected canonical '{TMDB}pb', got '{brando_cluster['canonical']}'"
    assert CSV_NS + "csv_p3" in brando_cluster["members"]


def test_miramax_properties():
    """Miramax Films should have foundingDate and headquarter from its source."""
    g = load_fused_graph()
    founded = [str(o) for o in g.objects(URIRef(JSON_NS + "json_c1"), URIRef(ONTO + "foundingDate"))]
    assert "1979" in founded, f"Expected foundingDate '1979' for Miramax, got {founded}"
    hq = [str(o) for o in g.objects(URIRef(JSON_NS + "json_c1"), URIRef(ONTO + "headquarter"))]
    assert "Los Angeles" in hq, f"Expected headquarter 'Los Angeles' for Miramax, got {hq}"


def test_inception_distribution():
    """Inception should have Warner Bros. as distribution."""
    g = load_fused_graph()
    dist = [str(o) for o in g.objects(URIRef(TMDB + "f3"), URIRef(ONTO + "distribution"))]
    assert TMDB + "cw" in dist, f"Expected '{TMDB}cw' in distribution, got {dist}"


def test_paramount_merged():
    """Paramount Pictures from CSV should be merged into the seed entity."""
    g = load_fused_graph()
    triples = list(g.triples((URIRef(CSV_NS + "csv_c1"), None, None)))
    assert len(triples) == 0, \
        f"csv_c1 (Paramount) should be merged into seed:c1, but found {len(triples)} triples"


def test_thurman_merged():
    """Uma Thurman from CSV should be merged with the RDF source entity."""
    g = load_fused_graph()
    triples = list(g.triples((URIRef(CSV_NS + "csv_p5"), None, None)))
    assert len(triples) == 0, \
        f"csv_p5 (Thurman) should be merged, but found {len(triples)} triples"


def test_nolan_merged():
    """Christopher Nolan from CSV should be merged with the RDF source entity."""
    g = load_fused_graph()
    triples = list(g.triples((URIRef(CSV_NS + "csv_p6"), None, None)))
    assert len(triples) == 0, \
        f"csv_p6 (Nolan) should be merged, but found {len(triples)} triples"


def test_pulp_fiction_gross():
    """Pulp Fiction gross should reflect the correct resolved value."""
    g = load_fused_graph()
    gross_vals = list(g.objects(URIRef(SEED + "m2"), URIRef(ONTO + "gross")))
    assert len(gross_vals) == 1, f"Expected 1 gross value for Pulp Fiction, got {len(gross_vals)}"
    assert str(gross_vals[0]) == "213928762", f"Expected '213928762', got '{gross_vals[0]}'"


def test_tarantino_properties():
    """Tarantino should have correctly merged properties from all sources."""
    g = load_fused_graph()
    dates = list(g.objects(URIRef(SEED + "p2"), URIRef(ONTO + "birthDate")))
    assert len(dates) == 1, f"Expected 1 birthDate for Tarantino, got {len(dates)}"
    assert str(dates[0]) == "1963-03-27"
    places = [str(o) for o in g.objects(URIRef(SEED + "p2"), URIRef(ONTO + "birthPlace"))]
    assert "Knoxville" in places


def test_brando_properties():
    """Brando should have correctly merged properties."""
    g = load_fused_graph()
    dates = list(g.objects(URIRef(TMDB + "pb"), URIRef(ONTO + "birthDate")))
    assert len(dates) == 1, f"Expected 1 birthDate for Brando, got {len(dates)}"
    assert str(dates[0]) == "1924-04-03"
    occ = [str(o) for o in g.objects(URIRef(TMDB + "pb"), URIRef(ONTO + "occupation"))]
    assert "Actor" in occ
