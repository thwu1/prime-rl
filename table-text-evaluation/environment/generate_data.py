#!/usr/bin/env python3
"""Generate synthetic LATTE-format dataset for table-text relatedness benchmark."""
import json
import csv
import hashlib
import os
import random

random.seed(42)


def make_id(text):
    return hashlib.md5(text.encode('utf-8')).hexdigest()


os.makedirs('/benchmark_data', exist_ok=True)

# ─── Tables ──────────────────────────────────────────────────────────────────
TABLES_RAW = [
    {
        "title": "Fortune 500 Companies 2024",
        "url": "https://en.wikipedia.org/wiki/Fortune_500",
        "header": ["Rank", "Company", "Revenue ($B)", "Industry"],
        "rows": [
            ["1", "Walmart", "648", "Retail"],
            ["2", "Amazon", "575", "Technology"],
            ["3", "Apple", "383", "Technology"],
            ["4", "UnitedHealth Group", "372", "Healthcare"],
            ["5", "Berkshire Hathaway", "365", "Conglomerate"],
        ],
    },
    {
        "title": "2024 Paris Olympics Medal Table",
        "url": "https://en.wikipedia.org/wiki/2024_Summer_Olympics",
        "header": ["Rank", "Country", "Gold", "Silver", "Bronze", "Total"],
        "rows": [
            ["1", "United States", "40", "44", "42", "126"],
            ["2", "China", "40", "27", "24", "91"],
            ["3", "Great Britain", "14", "22", "29", "65"],
            ["4", "France", "16", "26", "22", "64"],
            ["5", "Australia", "18", "19", "16", "53"],
        ],
    },
    {
        "title": "Largest Cities by Population",
        "url": "https://en.wikipedia.org/wiki/Largest_cities",
        "header": ["City", "Country", "Population (M)", "Continent"],
        "rows": [
            ["Tokyo", "Japan", "37.4", "Asia"],
            ["Delhi", "India", "32.9", "Asia"],
            ["Shanghai", "China", "28.5", "Asia"],
            ["Sao Paulo", "Brazil", "22.4", "South America"],
            ["Mexico City", "Mexico", "21.8", "North America"],
        ],
    },
    {
        "title": "Nobel Prize in Physics 2020-2024",
        "url": "https://en.wikipedia.org/wiki/Nobel_Prize_in_Physics",
        "header": ["Year", "Laureate", "Country", "Topic"],
        "rows": [
            ["2024", "Hopfield and Hinton", "USA and Canada", "Neural Networks"],
            ["2023", "Agostini Krausz L'Huillier", "France Austria Sweden", "Attosecond Pulses"],
            ["2022", "Aspect Clauser Zeilinger", "France USA Austria", "Quantum Entanglement"],
            ["2021", "Manabe Hasselmann Parisi", "Japan Germany Italy", "Climate Modelling"],
            ["2020", "Penrose Genzel Ghez", "UK Germany USA", "Black Holes"],
        ],
    },
    {
        "title": "Major Programming Languages",
        "url": "https://en.wikipedia.org/wiki/Programming_language",
        "header": ["Language", "Year", "Creator", "Paradigm"],
        "rows": [
            ["Python", "1991", "Guido van Rossum", "Multi-paradigm"],
            ["JavaScript", "1995", "Brendan Eich", "Multi-paradigm"],
            ["Java", "1995", "James Gosling", "Object-oriented"],
            ["C++", "1985", "Bjarne Stroustrup", "Multi-paradigm"],
            ["Rust", "2010", "Graydon Hoare", "Multi-paradigm"],
        ],
    },
    {
        "title": "Space Missions 2024",
        "url": "https://en.wikipedia.org/wiki/2024_in_spaceflight",
        "header": ["Mission", "Agency", "Destination", "Status"],
        "rows": [
            ["Artemis II", "NASA", "Lunar Orbit", "Scheduled"],
            ["Chang'e 6", "CNSA", "Moon Far Side", "Success"],
            ["Europa Clipper", "NASA", "Jupiter Europa", "En Route"],
            ["Starship IFT-3", "SpaceX", "Suborbital", "Partial Success"],
            ["SLIM", "JAXA", "Moon", "Success"],
        ],
    },
    {
        "title": "European Union GDP by Country",
        "url": "https://en.wikipedia.org/wiki/Economy_of_the_European_Union",
        "header": ["Country", "GDP ($B)", "Growth (%)", "Per Capita ($)"],
        "rows": [
            ["Germany", "4456", "0.3", "52824"],
            ["France", "3049", "1.1", "44408"],
            ["Italy", "2255", "0.9", "37146"],
            ["Spain", "1582", "2.5", "33090"],
            ["Netherlands", "1093", "0.7", "61098"],
        ],
    },
    {
        "title": "Major Rivers of the World",
        "url": "https://en.wikipedia.org/wiki/List_of_rivers_by_length",
        "header": ["River", "Length (km)", "Discharge (m3/s)", "Countries"],
        "rows": [
            ["Nile", "6650", "2830", "Egypt Sudan Ethiopia"],
            ["Amazon", "6400", "209000", "Brazil Peru Colombia"],
            ["Yangtze", "6300", "30000", "China"],
            ["Mississippi", "6275", "16800", "United States"],
            ["Yenisei", "5539", "19600", "Russia Mongolia"],
        ],
    },
    {
        "title": "Top Grossing Films of 2024",
        "url": "https://en.wikipedia.org/wiki/2024_in_film",
        "header": ["Rank", "Title", "Studio", "Worldwide Gross ($M)"],
        "rows": [
            ["1", "Inside Out 2", "Disney Pixar", "1699"],
            ["2", "Deadpool and Wolverine", "Marvel Disney", "1338"],
            ["3", "Despicable Me 4", "Universal", "969"],
            ["4", "Moana 2", "Disney", "950"],
            ["5", "Wicked", "Universal", "700"],
        ],
    },
    {
        "title": "Global Carbon Emissions by Sector",
        "url": "https://en.wikipedia.org/wiki/Greenhouse_gas_emissions",
        "header": ["Sector", "Emissions (GtCO2)", "Share (%)", "Trend"],
        "rows": [
            ["Energy", "15.8", "40.1", "Increasing"],
            ["Transport", "8.3", "21.1", "Increasing"],
            ["Industry", "6.2", "15.7", "Stable"],
            ["Buildings", "3.3", "8.4", "Decreasing"],
            ["Agriculture", "5.8", "14.7", "Increasing"],
        ],
    },
]

tables = []
for t in TABLES_RAW:
    t["id"] = make_id(t["title"])
    tables.append(t)

# ─── Texts ───────────────────────────────────────────────────────────────────
# Each text is topically related to one or more tables.
# Some share URLs with their related table (easy for URL matching).
# Some share entities but different URLs (needs entity overlap / TF-IDF).
TEXTS_RAW = [
    # Text 0 → Table 0 (Fortune 500). URL matches.
    {
        "text": "Walmart is the world's largest company by revenue at $648 billion. Amazon follows at $575 billion, while Apple rounds out the top three with $383 billion. UnitedHealth Group and Berkshire Hathaway also rank among the Fortune 500 top five. The retail and technology sectors dominate this year's list.",
        "url": "https://en.wikipedia.org/wiki/Fortune_500",
    },
    # Text 1 → Table 1 (Olympics). URL matches.
    {
        "text": "The 2024 Paris Olympics saw the United States and China tied at 40 gold medals each. The United States led the overall medal count with 126 total medals compared to China's 91. France, as host nation, earned 16 gold medals, while Great Britain and Australia completed the top five.",
        "url": "https://en.wikipedia.org/wiki/2024_Summer_Olympics",
    },
    # Text 2 → Table 2 (Cities). Different URL, entity overlap.
    {
        "text": "Tokyo remains the world's most populous metropolitan area with 37.4 million residents in the greater area. Delhi has grown rapidly to 32.9 million, surpassing Shanghai at 28.5 million. These Asian megacities face significant infrastructure and sustainability challenges as urbanization accelerates across the continent.",
        "url": "https://en.wikipedia.org/wiki/Megacity",
    },
    # Text 3 → Table 3 (Nobel). URL matches.
    {
        "text": "The 2024 Nobel Prize in Physics was awarded jointly to John Hopfield and Geoffrey Hinton for foundational discoveries enabling machine learning with artificial neural networks. Previous years recognized work on attosecond pulses of light, quantum entanglement experiments, and climate modelling of complex physical systems.",
        "url": "https://en.wikipedia.org/wiki/Nobel_Prize_in_Physics",
    },
    # Text 4 → Table 4 (Programming). Different URL, entity overlap.
    {
        "text": "Python, created by Guido van Rossum in 1991, continues to dominate software development. JavaScript and Java remain among the most widely deployed languages. Newer entrants like Rust, designed by Graydon Hoare at Mozilla, have gained traction for systems programming due to memory safety guarantees without garbage collection overhead.",
        "url": "https://en.wikipedia.org/wiki/Software_development",
    },
    # Text 5 → Table 5 (Space). URL matches.
    {
        "text": "NASA's Europa Clipper launched in October 2024 to study Jupiter's moon Europa for signs of habitability. China's CNSA achieved a major milestone with Chang'e 6 returning samples from the Moon's far side. SpaceX's Starship IFT-3 flight demonstrated significant progress despite being classified as a partial success. JAXA's SLIM lander also reached the Moon.",
        "url": "https://en.wikipedia.org/wiki/2024_in_spaceflight",
    },
    # Text 6 → Table 6 (EU GDP). URL matches.
    {
        "text": "Germany leads the European Union with a GDP of $4.456 trillion, though growth was modest at 0.3 percent. Spain showed the strongest performance at 2.5 percent growth. France at $3.049 trillion and Italy at $2.255 trillion recorded intermediate growth rates. The Netherlands achieved the highest GDP per capita among major EU economies at $61,098.",
        "url": "https://en.wikipedia.org/wiki/Economy_of_the_European_Union",
    },
    # Text 7 → Table 7 (Rivers). Different URL, entity overlap.
    {
        "text": "The Nile stretches approximately 6,650 kilometers through northeastern Africa, making it one of the longest rivers in the world. The Amazon, though slightly shorter at 6,400 km, has an enormous discharge of 209,000 cubic meters per second, dwarfing all other rivers. The Yangtze and Mississippi also rank among the great rivers by length.",
        "url": "https://en.wikipedia.org/wiki/River",
    },
    # Text 8 → Table 8 (Films). URL matches.
    {
        "text": "Inside Out 2 from Disney Pixar became the highest-grossing film of 2024 with $1.699 billion worldwide. Deadpool and Wolverine earned $1.338 billion for Marvel Disney. Universal's Despicable Me 4 reached $969 million. Animation dominated the top of the box office, with Moana 2 and Wicked rounding out the top five.",
        "url": "https://en.wikipedia.org/wiki/2024_in_film",
    },
    # Text 9 → Table 9 (Emissions). URL matches.
    {
        "text": "Global carbon dioxide emissions reached record levels, with the energy sector contributing 40.1 percent of total CO2 at 15.8 GtCO2. Transport follows at 21.1 percent and industry at 15.7 percent. Only the buildings sector shows a decreasing emissions trend. Agriculture continues to increase its share of greenhouse gas output.",
        "url": "https://en.wikipedia.org/wiki/Greenhouse_gas_emissions",
    },
    # Text 10 → Tables 0, 4 (Fortune 500 + Programming). Entity overlap with both.
    {
        "text": "The technology sector dominates both the Fortune 500 revenue rankings and the programming language ecosystem. Companies like Amazon and Apple leverage Python and Java extensively in their engineering stacks. Walmart has invested heavily in technology infrastructure, while Berkshire Hathaway increasingly views tech as a core investment thesis.",
        "url": "https://en.wikipedia.org/wiki/Technology_industry",
    },
    # Text 11 → Tables 7, 9 (Rivers + Emissions). Entity overlap with both.
    {
        "text": "Climate change threatens major river systems worldwide. The Nile basin faces altered rainfall patterns, while the Amazon rainforest acts as a critical carbon sink. Rising greenhouse gas emissions from energy and transport sectors directly impact water cycles. The Mississippi River watershed is increasingly affected by extreme weather events linked to global warming.",
        "url": "https://en.wikipedia.org/wiki/Climate_change",
    },
    # Text 12 → Table 8 (Films). Entity overlap, different URL.
    {
        "text": "The global film industry experienced a strong rebound in 2024, driven primarily by animated features. Inside Out 2 and Moana 2 from Disney proved the enduring appeal of family entertainment. Universal found success with both Despicable Me 4 and Wicked, a live-action musical adaptation. Marvel's Deadpool franchise continued to perform well.",
        "url": "https://en.wikipedia.org/wiki/Film_industry",
    },
    # Text 13 → Table 5 (Space). Entity overlap, different URL.
    {
        "text": "Space exploration entered a transformative phase in 2024 with multiple lunar missions. NASA's Artemis program continued preparations for crewed flights to the Moon. International agencies including CNSA, JAXA, and SpaceX achieved significant milestones. The Europa Clipper mission represents NASA's most ambitious outer solar system exploration in decades.",
        "url": "https://en.wikipedia.org/wiki/Space_exploration",
    },
    # Text 14 → Table 6 (EU GDP). Entity overlap, different URL.
    {
        "text": "European monetary policy in 2024 balanced inflation control with growth support. Germany's economy stagnated at 0.3 percent growth while Spain outperformed at 2.5 percent. The Netherlands achieved remarkable GDP per capita of $61,098. France and Italy maintained steady but unspectacular economic performance within the eurozone.",
        "url": "https://en.wikipedia.org/wiki/Eurozone",
    },
]

texts = []
for t in TEXTS_RAW:
    t["text_id"] = make_id(t["text"][:60])
    texts.append(t)

# ─── Pairs ───────────────────────────────────────────────────────────────────
# Positive associations: text_index -> [table_indices]
POSITIVE_MAP = {
    0: [0],
    1: [1],
    2: [2],
    3: [3],
    4: [4],
    5: [5],
    6: [6],
    7: [7],
    8: [8],
    9: [9],
    10: [0, 4],
    11: [7, 9],
    12: [8],
    13: [5],
    14: [6],
}

all_pairs = []
seen = set()

# Add positive pairs
for text_idx, table_indices in POSITIVE_MAP.items():
    for table_idx in table_indices:
        key = (texts[text_idx]["text_id"], tables[table_idx]["id"])
        if key not in seen:
            seen.add(key)
            all_pairs.append((key[0], key[1], 1))

# Add negative pairs (5 per text from non-positive tables)
for text_idx in range(len(texts)):
    positive_tables = set(POSITIVE_MAP.get(text_idx, []))
    negative_tables = [i for i in range(len(tables)) if i not in positive_tables]
    random.shuffle(negative_tables)
    for table_idx in negative_tables[:5]:
        key = (texts[text_idx]["text_id"], tables[table_idx]["id"])
        if key not in seen:
            seen.add(key)
            all_pairs.append((key[0], key[1], 0))

# ─── Write output ────────────────────────────────────────────────────────────
with open("/benchmark_data/tables.json", "w") as f:
    json.dump(tables, f, indent=2)

with open("/benchmark_data/texts.json", "w") as f:
    json.dump(texts, f, indent=2)

with open("/benchmark_data/pairs.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["text_id", "table_id", "label"])
    for tid, tabid, label in all_pairs:
        writer.writerow([tid, tabid, label])

n_pos = sum(1 for _, _, l in all_pairs if l == 1)
n_neg = sum(1 for _, _, l in all_pairs if l == 0)
print(f"Generated {len(tables)} tables, {len(texts)} texts, {len(all_pairs)} pairs ({n_pos} pos, {n_neg} neg)")
