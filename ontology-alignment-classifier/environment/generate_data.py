#!/usr/bin/env python3
"""Generate ontology alignment task data with complex OWL DL axioms."""
import os
import csv

def xml_escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")

SOURCE_NS = "http://example.org/retailprod"
TARGET_NS = "http://example.org/industrialsupply"

# (id, label, parent_id_or_None, description, [alt_labels])
SOURCE_CLASSES = [
    ("RP_001", "Product", None, "Any retail product", ["Retail Item"]),
    ("RP_010", "Food and Beverages", "RP_001", "Consumable food and drink items", ["F and B", "Edibles"]),
    ("RP_011", "Fresh Produce", "RP_010", "Fresh fruits and vegetables", ["Farm Fresh"]),
    ("RP_012", "Fruits", "RP_011", "Fresh edible fruits", ["Fresh Fruit Products"]),
    ("RP_013", "Citrus Fruits", "RP_012", "Oranges, lemons, limes, grapefruits", []),
    ("RP_014", "Tropical Fruits", "RP_012", "Mangoes, papayas, pineapples", []),
    ("RP_015", "Stone Fruits", "RP_012", "Peaches, plums, cherries, apricots", ["Drupes"]),
    ("RP_016", "Berries", "RP_012", "Strawberries, blueberries, raspberries", ["Small Fruits"]),
    ("RP_017", "Vegetables", "RP_011", "Fresh edible vegetables", []),
    ("RP_018", "Leafy Greens", "RP_017", "Lettuce, spinach, kale, arugula", ["Salad Vegetables"]),
    ("RP_019", "Root Vegetables", "RP_017", "Carrots, potatoes, beets, turnips", ["Tubers"]),
    ("RP_020", "Herbs and Spices", "RP_011", "Fresh culinary herbs and dried spices", ["Seasonings"]),
    ("RP_030", "Dairy Products", "RP_010", "Milk-based products", ["Dairy"]),
    ("RP_031", "Milk", "RP_030", "Liquid milk products", ["Fresh Milk"]),
    ("RP_032", "Cheese", "RP_030", "All cheese varieties", ["Fromage"]),
    ("RP_033", "Hard Cheese", "RP_032", "Cheddar, parmesan, gouda, gruyere", []),
    ("RP_034", "Soft Cheese", "RP_032", "Brie, camembert, cream cheese, ricotta", []),
    ("RP_035", "Yogurt", "RP_030", "Fermented milk yogurt products", ["Yoghurt"]),
    ("RP_036", "Butter and Margarine", "RP_030", "Spreadable fats from dairy sources", ["Spreads"]),
    ("RP_040", "Bakery Products", "RP_010", "Baked goods including bread, pastries, and cakes", ["Baked Goods"]),
    ("RP_041", "Bread", "RP_040", "Loaves, rolls, and flatbreads", ["Loaves"]),
    ("RP_042", "Pastries", "RP_040", "Croissants, danishes, puff pastry items", []),
    ("RP_043", "Cakes and Pies", "RP_040", "Sweet baked desserts and pies", []),
    ("RP_050", "Beverages", "RP_010", "Drinkable liquids for consumption", ["Drinks"]),
    ("RP_051", "Soft Drinks", "RP_050", "Carbonated non-alcoholic beverages", ["Soda", "Pop"]),
    ("RP_052", "Fruit Juices", "RP_050", "Extracted fruit liquids and nectars", ["Juice"]),
    ("RP_053", "Bottled Water", "RP_050", "Packaged drinking water", ["Mineral Water"]),
    ("RP_054", "Hot Beverages", "RP_050", "Coffee, tea, and cocoa drinks", ["Warm Drinks"]),
    ("RP_055", "Coffee", "RP_054", "Coffee beans, ground coffee, and instant", []),
    ("RP_056", "Tea", "RP_054", "Tea leaves, tea bags, and herbal infusions", []),
    ("RP_060", "Meat and Seafood", "RP_010", "Animal protein products for consumption", ["Protein"]),
    ("RP_061", "Red Meat", "RP_060", "Beef, lamb, and pork products", []),
    ("RP_062", "Beef", "RP_061", "Cattle meat products and cuts", ["Cattle Meat"]),
    ("RP_063", "Pork", "RP_061", "Pig meat products and cuts", ["Swine"]),
    ("RP_064", "Poultry", "RP_060", "Chicken, turkey, duck, and goose", ["Fowl"]),
    ("RP_065", "Seafood", "RP_060", "Fish and shellfish from aquatic sources", ["Marine Products"]),
    ("RP_066", "Fish", "RP_065", "Finfish products including fillets and steaks", []),
    ("RP_067", "Shellfish", "RP_065", "Shrimp, crab, lobster, mussels, oysters", ["Crustaceans"]),
    ("RP_070", "Snack Foods", "RP_010", "Between-meal food items and treats", ["Snacks"]),
    ("RP_071", "Chips and Crisps", "RP_070", "Fried or baked sliced potato and corn snacks", ["Potato Chips"]),
    ("RP_072", "Nuts and Seeds", "RP_070", "Edible nuts and seeds for snacking", ["Trail Mix"]),
    ("RP_073", "Confectionery", "RP_070", "Candy, chocolate, and sugar-based sweets", ["Sweets", "Candy"]),
    ("RP_074", "Chocolate", "RP_073", "Cocoa-based confections and bars", []),
    ("RP_080", "Frozen Foods", "RP_010", "Commercially frozen food products", ["Freezer Items"]),
    ("RP_081", "Frozen Vegetables", "RP_080", "Frozen vegetable products and mixes", []),
    ("RP_082", "Frozen Meals", "RP_080", "Ready-to-heat frozen complete dishes", ["TV Dinners"]),
    ("RP_083", "Ice Cream", "RP_080", "Frozen dairy-based desserts", ["Gelato"]),
    ("RP_100", "Household Products", "RP_001", "Home care, maintenance, and cleaning supplies", ["Home Care"]),
    ("RP_110", "Cleaning Products", "RP_100", "Cleaning agents, tools, and supplies", ["Cleaners"]),
    ("RP_111", "Surface Cleaners", "RP_110", "Sprays and wipes for counters and surfaces", []),
    ("RP_112", "Laundry Products", "RP_110", "Detergents, fabric softeners, and stain removers", ["Laundry Supplies"]),
    ("RP_113", "Dishwashing Products", "RP_110", "Dish soap, dishwasher tablets, and rinse aid", []),
    ("RP_114", "Floor Cleaners", "RP_110", "Mops, floor polish, and floor cleaning solutions", []),
    ("RP_120", "Paper Products", "RP_100", "Disposable consumer paper goods", []),
    ("RP_121", "Facial Tissues", "RP_120", "Soft tissue papers for facial use", ["Kleenex"]),
    ("RP_122", "Paper Towels", "RP_120", "Absorbent paper towels for kitchen and cleaning", []),
    ("RP_123", "Toilet Paper", "RP_120", "Bathroom tissue rolls", ["Bath Tissue"]),
    ("RP_124", "Napkins", "RP_120", "Paper napkins for dining", ["Serviettes"]),
    ("RP_200", "Personal Care", "RP_001", "Body care, hygiene, and grooming products", ["Body Care"]),
    ("RP_210", "Skin Care", "RP_200", "Products for skin health and appearance", []),
    ("RP_211", "Moisturizers", "RP_210", "Skin hydration creams and lotions", ["Hydrating Cream"]),
    ("RP_212", "Sunscreen", "RP_210", "UV protection products for skin", ["Sun Block"]),
    ("RP_213", "Facial Cleansers", "RP_210", "Face washing products and toners", []),
    ("RP_220", "Hair Care", "RP_200", "Products for hair washing, conditioning, and styling", []),
    ("RP_221", "Shampoo", "RP_220", "Hair washing and cleansing products", []),
    ("RP_222", "Conditioner", "RP_220", "Hair conditioning and detangling products", []),
    ("RP_223", "Hair Styling", "RP_220", "Gels, sprays, mousses, and wax for hair", []),
    ("RP_230", "Oral Care", "RP_200", "Dental and oral hygiene products", ["Dental Hygiene"]),
    ("RP_231", "Toothpaste", "RP_230", "Tooth cleaning paste and gel", []),
    ("RP_232", "Toothbrushes", "RP_230", "Manual and electric toothbrushes", []),
    ("RP_233", "Mouthwash", "RP_230", "Oral rinse and antiseptic solutions", []),
    ("RP_240", "Bath and Body", "RP_200", "Body washing, soap, and deodorant products", []),
    ("RP_241", "Body Wash", "RP_240", "Liquid body cleansers and shower gels", ["Shower Gel"]),
    ("RP_242", "Bar Soap", "RP_240", "Solid soap bars for body washing", []),
    ("RP_243", "Deodorant", "RP_240", "Body odor prevention products", ["Antiperspirant"]),
    ("RP_300", "Electronics", "RP_001", "Electronic devices, gadgets, and accessories", ["Consumer Electronics"]),
    ("RP_310", "Computing Devices", "RP_300", "Computers, tablets, and peripherals", ["Computers"]),
    ("RP_311", "Laptops", "RP_310", "Portable notebook computers", ["Notebook Computers"]),
    ("RP_312", "Desktop Computers", "RP_310", "Stationary personal computer systems", ["PCs"]),
    ("RP_313", "Tablets", "RP_310", "Touchscreen tablet computing devices", ["Tablet PCs"]),
    ("RP_314", "Computer Accessories", "RP_310", "Keyboards, mice, monitors, and peripherals", ["Peripherals"]),
    ("RP_320", "Mobile Devices", "RP_300", "Portable communication and smart devices", []),
    ("RP_321", "Smartphones", "RP_320", "Mobile phones with advanced computing capabilities", ["Mobile Handsets"]),
    ("RP_322", "Phone Accessories", "RP_320", "Cases, chargers, and screen protectors for phones", []),
    ("RP_330", "Audio and Video", "RP_300", "Entertainment audio and video electronics", ["AV Equipment"]),
    ("RP_331", "Headphones", "RP_330", "Personal audio listening devices and earbuds", []),
    ("RP_332", "Speakers", "RP_330", "Audio output and amplification devices", []),
    ("RP_333", "Televisions", "RP_330", "Television display units and smart TVs", ["TVs"]),
    ("RP_334", "Cameras", "RP_330", "Digital imaging and photography devices", []),
]

TARGET_CLASSES = [
    ("IS_001", "Commercial Product", None, "Any commercial or industrial product", ["Trade Good"]),
    ("IS_010", "Consumable Food Products", "IS_001", "Products intended for human consumption", ["Food Items"]),
    ("IS_011", "Agricultural Produce", "IS_010", "Farm-grown food products including grains and cereals", ["Farm Products"]),
    ("IS_012", "Fresh Fruit", "IS_011", "Unprocessed edible fruits", ["Fruit Products"]),
    ("IS_013", "Citrus Variety Fruits", "IS_012", "Orange, lemon, grapefruit, lime, tangerine", []),
    ("IS_014", "Tropical and Exotic Fruits", "IS_012", "Mango, papaya, guava, passion fruit, lychee", []),
    ("IS_015", "Temperate Climate Fruits", "IS_012", "Apples, pears, stone fruits, and berries", ["Deciduous Fruits"]),
    ("IS_016", "Fresh Vegetables and Legumes", "IS_011", "Unprocessed vegetables including legumes and pulses", []),
    ("IS_017", "Leaf and Stem Vegetables", "IS_016", "Lettuce, cabbage, celery, spinach, kale", ["Leafy Vegetables"]),
    ("IS_018", "Tuber and Root Crops", "IS_016", "Potato, carrot, turnip, yam, cassava, beet", []),
    ("IS_019", "Legumes and Pulses", "IS_016", "Beans, lentils, peas, chickpeas, soybeans", []),
    ("IS_020", "Cereal Grains", "IS_011", "Wheat, rice, corn, barley, oats, rye", ["Grain Products"]),
    ("IS_021", "Culinary Herbs", "IS_011", "Fresh basil, parsley, cilantro, dill, mint", []),
    ("IS_022", "Dried Spices", "IS_011", "Pepper, cinnamon, cumin, turmeric, paprika", ["Ground Spices"]),
    ("IS_030", "Animal-Derived Food", "IS_010", "Food products sourced from animals", []),
    ("IS_031", "Dairy and Milk Products", "IS_030", "Milk and all milk-derived food products", ["Dairy Goods"]),
    ("IS_032", "Liquid Milk", "IS_031", "Whole, skimmed, semi-skimmed, and flavored milk", []),
    ("IS_033", "Cheese Products", "IS_031", "All varieties and types of cheese", []),
    ("IS_034", "Fermented Dairy", "IS_031", "Yogurt, kefir, buttermilk, and sour cream", []),
    ("IS_035", "Dairy Fats", "IS_031", "Butter, ghee, cream, and dairy-based spreads", []),
    ("IS_036", "Meat Products", "IS_030", "All meat from domesticated land animals", []),
    ("IS_037", "Bovine Meat", "IS_036", "Beef and veal products and cuts", ["Beef"]),
    ("IS_038", "Swine Meat", "IS_036", "Pork, ham, and bacon products", ["Pork Products"]),
    ("IS_039", "Poultry Meat", "IS_036", "Chicken, turkey, duck, and goose meat", []),
    ("IS_040", "Ovine Meat", "IS_036", "Lamb and mutton products and cuts", []),
    ("IS_041", "Marine Food Products", "IS_030", "Food products from oceans, rivers, and lakes", ["Aquatic Foods"]),
    ("IS_042", "Finfish", "IS_041", "Salmon, tuna, cod, tilapia, trout, mackerel", []),
    ("IS_043", "Crustaceans and Mollusks", "IS_041", "Shrimp, crab, lobster, oyster, squid, mussels", ["Shellfish Products"]),
    ("IS_044", "Eggs", "IS_030", "Poultry eggs for human consumption", []),
    ("IS_050", "Processed Food Products", "IS_010", "Industrially processed and packaged foods", []),
    ("IS_051", "Baked Goods", "IS_050", "Commercially baked bread, rolls, pastries, and cakes", []),
    ("IS_052", "Bread and Rolls", "IS_051", "Leavened and unleavened breads and dinner rolls", []),
    ("IS_053", "Sweet Baked Goods", "IS_051", "Cakes, cookies, pastries, muffins, and pies", []),
    ("IS_054", "Confections and Sweets", "IS_050", "Candy, chocolate, sugar confections, and gum", []),
    ("IS_055", "Chocolate Products", "IS_054", "Chocolate bars, truffles, and cocoa products", []),
    ("IS_056", "Preserved Foods", "IS_050", "Canned, dried, pickled, and jarred foods", []),
    ("IS_057", "Frozen Food Products", "IS_050", "Commercially frozen foods for retail and foodservice", []),
    ("IS_058", "Frozen Prepared Meals", "IS_057", "Ready-to-heat frozen complete dishes and entrees", []),
    ("IS_059", "Frozen Produce", "IS_057", "Frozen fruits, vegetables, and herb mixes", []),
    ("IS_060", "Frozen Desserts", "IS_057", "Ice cream, sorbet, frozen yogurt, and popsicles", []),
    ("IS_061", "Snack Products", "IS_050", "Packaged snack items for between-meal consumption", []),
    ("IS_062", "Savory Snacks", "IS_061", "Chips, crackers, pretzels, and popcorn", []),
    ("IS_063", "Nut and Seed Products", "IS_061", "Packaged nuts, seeds, and trail mix blends", []),
    ("IS_070", "Beverage Products", "IS_010", "All drinkable commercial products", ["Drinks"]),
    ("IS_071", "Carbonated Drinks", "IS_070", "Fizzy soft drinks, sodas, and sparkling water", ["Fizzy Drinks"]),
    ("IS_072", "Juice Products", "IS_070", "Fruit juices, vegetable juices, and smoothies", []),
    ("IS_073", "Packaged Water", "IS_070", "Bottled, canned, and packaged drinking water", []),
    ("IS_074", "Hot Beverage Products", "IS_070", "Coffee, tea, and hot chocolate products", []),
    ("IS_075", "Coffee Products", "IS_074", "Roasted beans, ground coffee, instant, and pods", []),
    ("IS_076", "Tea Products", "IS_074", "Loose leaf, bagged, and instant tea products", []),
    ("IS_100", "Chemical Products", "IS_001", "Chemical, cleaning, and hygiene products", []),
    ("IS_110", "Cleaning and Sanitation Chemicals", "IS_100", "Industrial and consumer cleaning compounds and disinfectants", ["Cleaning Compounds"]),
    ("IS_111", "General Purpose Cleaners", "IS_110", "Multi-surface cleaning solutions and sprays", []),
    ("IS_112", "Laundry Chemicals", "IS_110", "Detergents, bleach, fabric softeners, and stain removers", []),
    ("IS_113", "Dishwashing Compounds", "IS_110", "Manual and automatic dishwashing products", []),
    ("IS_114", "Floor Care Products", "IS_110", "Floor cleaners, polishes, wax, and strippers", []),
    ("IS_115", "Disinfectants and Sanitizers", "IS_110", "Antimicrobial cleaning and sanitizing agents", []),
    ("IS_120", "Personal Hygiene Products", "IS_100", "Body care, grooming, and hygiene items", []),
    ("IS_121", "Skin Care Products", "IS_120", "Lotions, creams, serums, and skin treatments", []),
    ("IS_122", "Moisturizing Products", "IS_121", "Skin hydration creams, lotions, and balms", []),
    ("IS_123", "Sun Protection Products", "IS_121", "Sunscreen, sunblock, and after-sun products", []),
    ("IS_124", "Facial Cleaning Products", "IS_121", "Face wash, cleansing wipes, and toners", []),
    ("IS_125", "Hair Care Products", "IS_120", "Shampoo, conditioner, and hair treatments", []),
    ("IS_126", "Hair Washing Products", "IS_125", "Shampoos and co-wash cleansing products", []),
    ("IS_127", "Hair Conditioning Products", "IS_125", "Conditioners, hair masks, and detanglers", []),
    ("IS_128", "Hair Styling Products", "IS_125", "Gel, mousse, spray, wax, and pomade", []),
    ("IS_129", "Dental Care Products", "IS_120", "Oral hygiene and dental health products", []),
    ("IS_130", "Toothpaste and Tooth Gel", "IS_129", "Tooth cleaning compounds and whitening pastes", []),
    ("IS_131", "Dental Brushes", "IS_129", "Manual and powered toothbrushes and interdental brushes", []),
    ("IS_132", "Oral Rinse Products", "IS_129", "Mouthwash, oral antiseptics, and fluoride rinses", []),
    ("IS_133", "Body Cleansing Products", "IS_120", "Soap, body wash, shower gel, and bath products", []),
    ("IS_134", "Liquid Body Cleanser", "IS_133", "Shower gels, body wash, and liquid soap", ["Body Wash", "Shower Gel"]),
    ("IS_135", "Solid Soap", "IS_133", "Bar soap, specialty soaps, and glycerin soap", []),
    ("IS_136", "Antiperspirant and Deodorant", "IS_120", "Body odor and perspiration control products", []),
    ("IS_140", "Paper and Tissue Products", "IS_001", "Disposable and industrial paper products", []),
    ("IS_141", "Facial Tissue", "IS_140", "Soft tissue for facial and personal use", []),
    ("IS_142", "Paper Toweling", "IS_140", "Absorbent paper towels for kitchen and industrial use", []),
    ("IS_143", "Bathroom Tissue", "IS_140", "Toilet paper and bathroom tissue rolls", []),
    ("IS_144", "Table Napkins", "IS_140", "Disposable paper napkins for dining and catering", []),
    ("IS_145", "Industrial Paper Products", "IS_140", "Packaging paper, kraft paper, and industrial rolls", []),
    ("IS_200", "Technology Equipment", "IS_001", "Electronic, IT, and communication technology equipment", ["Tech Equipment"]),
    ("IS_210", "Information Technology Hardware", "IS_200", "Computers, servers, storage, networking, and peripherals", ["IT Hardware"]),
    ("IS_211", "Portable Computers", "IS_210", "Laptops, notebooks, and ultrabooks", ["Laptop Computers"]),
    ("IS_212", "Desktop Computer Systems", "IS_210", "Stationary PC systems and workstations", []),
    ("IS_213", "Tablet Computers", "IS_210", "Touchscreen tablet devices and e-readers", []),
    ("IS_214", "Computer Peripheral Devices", "IS_210", "Input/output devices: keyboards, mice, monitors, printers", []),
    ("IS_215", "Data Storage Devices", "IS_210", "Hard drives, SSDs, flash drives, and NAS devices", []),
    ("IS_216", "Networking Equipment", "IS_210", "Routers, switches, access points, and modems", []),
    ("IS_220", "Communication Devices", "IS_200", "Devices for voice and data communication", []),
    ("IS_221", "Mobile Phones", "IS_220", "Cellular phones, smartphones, and feature phones", ["Smartphones", "Cellular Phones"]),
    ("IS_222", "Phone Accessories", "IS_220", "Cases, chargers, screen guards, and mounts", []),
    ("IS_223", "Two-Way Radio Equipment", "IS_220", "Walkie-talkies, radio transceivers, and CB radios", []),
    ("IS_230", "Consumer Electronics", "IS_200", "Entertainment, media, and gaming consumer devices", []),
    ("IS_231", "Personal Audio Devices", "IS_230", "Headphones, earbuds, and personal audio players", []),
    ("IS_232", "Audio Amplification Equipment", "IS_230", "Speakers, amplifiers, soundbars, and receivers", []),
    ("IS_233", "Display and Television Sets", "IS_230", "TVs, monitors, projectors, and digital signage", []),
    ("IS_234", "Imaging and Camera Equipment", "IS_230", "Digital cameras, camcorders, and action cameras", []),
    ("IS_235", "Gaming Devices", "IS_230", "Consoles, handheld gaming, VR headsets, and controllers", []),
]

# Object properties
SOURCE_OBJ_PROPS = [
    ("hasSubProduct", "has sub product", "RP_001", "RP_001"),
    ("isRelatedTo", "is related to", "RP_001", "RP_001"),
    ("hasQuality", "has quality state", "RP_001", "QualityState"),
    ("hasPackaging", "has packaging type", "RP_001", "PackagingType"),
]
SOURCE_DATA_PROPS = [
    ("retailPrice", "retail price", "RP_001", "xsd:decimal"),
    ("unitCount", "unit count", "RP_001", "xsd:integer"),
    ("shelfLife", "shelf life in days", "RP_010", "xsd:integer"),
]
TARGET_OBJ_PROPS = [
    ("hasComponent", "has component", "IS_001", "IS_001"),
    ("belongsToCategory", "belongs to category", "IS_001", "IS_001"),
    ("hasProcessingLevel", "has processing level", "IS_001", "ProcessingLevel"),
    ("requiresHandling", "requires handling type", "IS_001", "HandlingRequirement"),
]
TARGET_DATA_PROPS = [
    ("catalogCode", "catalog code", "IS_001", "xsd:string"),
    ("standardUnit", "standard unit of measure", "IS_001", "xsd:string"),
    ("hazardClassification", "hazard classification", "IS_100", "xsd:string"),
]

# Auxiliary classes used as restriction fillers
SOURCE_AUX_CLASSES = [
    ("QualityState", "Base class for product quality states"),
    ("FreshState", "Indicates fresh, unprocessed, perishable quality state"),
    ("FrozenState", "Indicates commercially frozen preservation state"),
    ("ProcessedState", "Indicates industrially processed state"),
    ("ChilledState", "Indicates refrigerated chilled storage state"),
    ("PackagingType", "Base class for product packaging types"),
    ("IndividualPortion", "Single-serving individual packaging format"),
    ("BulkPackaging", "Multi-unit or bulk packaging format"),
]

TARGET_AUX_CLASSES = [
    ("ProcessingLevel", "Base class for material processing levels"),
    ("RawMaterial", "Unprocessed raw agricultural or natural material"),
    ("IndustriallyProcessed", "Material that has undergone industrial processing"),
    ("HandlingRequirement", "Base class for handling and storage requirements"),
    ("ColdChainHandling", "Requires continuous refrigerated or frozen temperature chain"),
    ("AmbientHandling", "Suitable for ambient room temperature storage and handling"),
    ("HazmatHandling", "Requires hazardous material handling and classification procedures"),
]

# Equivalent class axioms: (class_id, base_class_id, property_id, filler_class_id)
# These define classes via owl:equivalentClass = owl:intersectionOf(base_class, Restriction(property some filler))
SOURCE_EQUIV_CLASSES = [
    ("RP_011", "RP_010", "hasQuality", "FreshState"),
    ("RP_080", "RP_010", "hasQuality", "FrozenState"),
]

TARGET_EQUIV_CLASSES = [
    ("IS_011", "IS_010", "hasProcessingLevel", "RawMaterial"),
    ("IS_050", "IS_010", "hasProcessingLevel", "IndustriallyProcessed"),
    ("IS_057", "IS_050", "requiresHandling", "ColdChainHandling"),
]

# Additional restriction axioms as rdfs:subClassOf constraints
# (class_id, property_id, filler_class_id)
SOURCE_RESTRICTIONS = [
    ("RP_030", "hasQuality", "ChilledState"),
    ("RP_065", "hasQuality", "FreshState"),
    ("RP_070", "hasPackaging", "IndividualPortion"),
]

TARGET_RESTRICTIONS = [
    ("IS_031", "requiresHandling", "ColdChainHandling"),
    ("IS_041", "requiresHandling", "ColdChainHandling"),
    ("IS_100", "requiresHandling", "HazmatHandling"),
]

# Disjointness axioms
SOURCE_DISJOINTS = [
    ("RP_010", "RP_100"), ("RP_010", "RP_200"), ("RP_010", "RP_300"),
    ("RP_100", "RP_200"), ("RP_100", "RP_300"), ("RP_200", "RP_300"),
    ("RP_011", "RP_030"), ("RP_011", "RP_040"), ("RP_011", "RP_050"),
    ("RP_011", "RP_060"), ("RP_011", "RP_070"), ("RP_011", "RP_080"),
    ("RP_030", "RP_060"), ("RP_050", "RP_060"),
    ("RP_110", "RP_120"), ("RP_210", "RP_220"), ("RP_210", "RP_230"),
    ("RP_220", "RP_230"),
]
TARGET_DISJOINTS = [
    ("IS_010", "IS_100"), ("IS_010", "IS_140"), ("IS_010", "IS_200"),
    ("IS_100", "IS_140"), ("IS_100", "IS_200"), ("IS_140", "IS_200"),
    ("IS_011", "IS_030"), ("IS_011", "IS_050"), ("IS_011", "IS_070"),
    ("IS_030", "IS_050"), ("IS_030", "IS_070"), ("IS_050", "IS_070"),
    ("IS_110", "IS_120"), ("IS_210", "IS_220"), ("IS_210", "IS_230"),
    ("IS_220", "IS_230"),
]

# Reference sample: 18 labeled pairs (reduced from 25 to force generalization)
REFERENCE_SAMPLE = [
    ("RP_012", "IS_012", "="),
    ("RP_062", "IS_037", "="),
    ("RP_055", "IS_075", "="),
    ("RP_112", "IS_112", "="),
    ("RP_241", "IS_134", "="),
    ("RP_060", "IS_036", ">"),
    ("RP_020", "IS_021", ">"),
    ("RP_070", "IS_062", ">"),
    ("RP_015", "IS_015", "<"),
    ("RP_083", "IS_060", "<"),
    ("RP_120", "IS_140", "<"),
    ("RP_010", "IS_010", "~"),
    ("RP_300", "IS_200", "~"),
    ("RP_320", "IS_220", "~"),
    ("RP_012", "IS_110", "!"),
    ("RP_220", "IS_036", "!"),
    ("RP_200", "IS_010", "!"),
    ("RP_310", "IS_031", "!"),
]

# All 80 candidate pairs to classify
CANDIDATE_PAIRS = [
    ("RP_012", "IS_012"), ("RP_013", "IS_013"), ("RP_014", "IS_014"),
    ("RP_018", "IS_017"), ("RP_019", "IS_018"), ("RP_030", "IS_031"),
    ("RP_031", "IS_032"), ("RP_032", "IS_033"), ("RP_041", "IS_052"),
    ("RP_050", "IS_070"), ("RP_055", "IS_075"), ("RP_056", "IS_076"),
    ("RP_062", "IS_037"), ("RP_063", "IS_038"), ("RP_064", "IS_039"),
    ("RP_066", "IS_042"), ("RP_067", "IS_043"), ("RP_074", "IS_055"),
    ("RP_082", "IS_058"), ("RP_112", "IS_112"), ("RP_121", "IS_141"),
    ("RP_123", "IS_143"), ("RP_211", "IS_122"), ("RP_221", "IS_126"),
    ("RP_231", "IS_130"), ("RP_241", "IS_134"), ("RP_311", "IS_211"),
    ("RP_321", "IS_221"), ("RP_331", "IS_231"), ("RP_333", "IS_233"),
    ("RP_020", "IS_021"), ("RP_020", "IS_022"), ("RP_060", "IS_036"),
    ("RP_060", "IS_041"), ("RP_010", "IS_070"), ("RP_100", "IS_110"),
    ("RP_200", "IS_133"), ("RP_040", "IS_052"), ("RP_240", "IS_134"),
    ("RP_070", "IS_062"),
    ("RP_015", "IS_015"), ("RP_016", "IS_015"), ("RP_017", "IS_016"),
    ("RP_035", "IS_034"), ("RP_036", "IS_035"), ("RP_042", "IS_053"),
    ("RP_043", "IS_053"), ("RP_081", "IS_059"), ("RP_083", "IS_060"),
    ("RP_120", "IS_140"), ("RP_071", "IS_062"), ("RP_061", "IS_036"),
    ("RP_010", "IS_010"), ("RP_011", "IS_011"), ("RP_110", "IS_110"),
    ("RP_300", "IS_200"), ("RP_310", "IS_210"), ("RP_320", "IS_220"),
    ("RP_330", "IS_230"), ("RP_073", "IS_061"), ("RP_040", "IS_050"),
    ("RP_300", "IS_230"),
    ("RP_012", "IS_110"), ("RP_032", "IS_210"), ("RP_060", "IS_140"),
    ("RP_110", "IS_070"), ("RP_220", "IS_036"), ("RP_310", "IS_031"),
    ("RP_050", "IS_210"), ("RP_230", "IS_057"), ("RP_040", "IS_220"),
    ("RP_070", "IS_129"), ("RP_200", "IS_010"), ("RP_100", "IS_200"),
    ("RP_030", "IS_230"), ("RP_300", "IS_010"), ("RP_011", "IS_120"),
    ("RP_055", "IS_234"), ("RP_035", "IS_221"), ("RP_114", "IS_076"),
]


def generate_owl(classes, obj_props, data_props, disjoints, ns, title, desc, filepath,
                 aux_classes=None, equiv_classes=None, restrictions=None):
    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<rdf:RDF xmlns="' + ns + '#"')
    lines.append('     xml:base="' + ns + '"')
    lines.append('     xmlns:owl="http://www.w3.org/2002/07/owl#"')
    lines.append('     xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"')
    lines.append('     xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"')
    lines.append('     xmlns:xsd="http://www.w3.org/2001/XMLSchema#"')
    lines.append('     xmlns:skos="http://www.w3.org/2004/02/skos/core#"')
    lines.append('     xmlns:dc="http://purl.org/dc/elements/1.1/">')
    lines.append('')
    lines.append('    <owl:Ontology rdf:about="' + ns + '">')
    lines.append('        <dc:title>' + xml_escape(title) + '</dc:title>')
    lines.append('        <dc:description>' + xml_escape(desc) + '</dc:description>')
    lines.append('        <owl:versionInfo>1.0</owl:versionInfo>')
    lines.append('    </owl:Ontology>')
    lines.append('')

    # Object properties
    for pname, plabel, domain, range_ in obj_props:
        lines.append('    <owl:ObjectProperty rdf:about="' + ns + '#' + pname + '">')
        lines.append('        <rdfs:label>' + xml_escape(plabel) + '</rdfs:label>')
        lines.append('        <rdfs:domain rdf:resource="' + ns + '#' + domain + '"/>')
        lines.append('        <rdfs:range rdf:resource="' + ns + '#' + range_ + '"/>')
        lines.append('    </owl:ObjectProperty>')
        lines.append('')

    # Datatype properties
    for pname, plabel, domain, range_ in data_props:
        if range_.startswith("xsd:"):
            range_uri = "http://www.w3.org/2001/XMLSchema#" + range_[4:]
        else:
            range_uri = range_
        lines.append('    <owl:DatatypeProperty rdf:about="' + ns + '#' + pname + '">')
        lines.append('        <rdfs:label>' + xml_escape(plabel) + '</rdfs:label>')
        lines.append('        <rdfs:domain rdf:resource="' + ns + '#' + domain + '"/>')
        lines.append('        <rdfs:range rdf:resource="' + range_uri + '"/>')
        lines.append('    </owl:DatatypeProperty>')
        lines.append('')

    # Auxiliary classes (restriction fillers)
    if aux_classes:
        for aux_id, aux_desc in aux_classes:
            lines.append('    <owl:Class rdf:about="' + ns + '#' + aux_id + '">')
            lines.append('        <rdfs:label xml:lang="en">' + xml_escape(aux_id) + '</rdfs:label>')
            lines.append('        <rdfs:comment xml:lang="en">' + xml_escape(aux_desc) + '</rdfs:comment>')
            lines.append('    </owl:Class>')
            lines.append('')

    # Main classes
    for cls_id, label, parent, desc_text, alts in classes:
        lines.append('    <owl:Class rdf:about="' + ns + '#' + cls_id + '">')
        lines.append('        <rdfs:label xml:lang="en">' + xml_escape(label) + '</rdfs:label>')
        lines.append('        <rdfs:comment xml:lang="en">' + xml_escape(desc_text) + '</rdfs:comment>')
        if parent:
            lines.append('        <rdfs:subClassOf rdf:resource="' + ns + '#' + parent + '"/>')
        for alt in alts:
            lines.append('        <skos:altLabel xml:lang="en">' + xml_escape(alt) + '</skos:altLabel>')
        lines.append('    </owl:Class>')
        lines.append('')

    # Equivalent class axioms (owl:equivalentClass with intersectionOf + Restriction)
    if equiv_classes:
        for cls_id, base_cls, prop, filler in equiv_classes:
            lines.append('    <rdf:Description rdf:about="' + ns + '#' + cls_id + '">')
            lines.append('        <owl:equivalentClass>')
            lines.append('            <owl:Class>')
            lines.append('                <owl:intersectionOf rdf:parseType="Collection">')
            lines.append('                    <owl:Class rdf:about="' + ns + '#' + base_cls + '"/>')
            lines.append('                    <owl:Restriction>')
            lines.append('                        <owl:onProperty rdf:resource="' + ns + '#' + prop + '"/>')
            lines.append('                        <owl:someValuesFrom rdf:resource="' + ns + '#' + filler + '"/>')
            lines.append('                    </owl:Restriction>')
            lines.append('                </owl:intersectionOf>')
            lines.append('            </owl:Class>')
            lines.append('        </owl:equivalentClass>')
            lines.append('    </rdf:Description>')
            lines.append('')

    # Restriction axioms (rdfs:subClassOf owl:Restriction)
    if restrictions:
        for cls_id, prop, filler in restrictions:
            lines.append('    <rdf:Description rdf:about="' + ns + '#' + cls_id + '">')
            lines.append('        <rdfs:subClassOf>')
            lines.append('            <owl:Restriction>')
            lines.append('                <owl:onProperty rdf:resource="' + ns + '#' + prop + '"/>')
            lines.append('                <owl:someValuesFrom rdf:resource="' + ns + '#' + filler + '"/>')
            lines.append('            </owl:Restriction>')
            lines.append('        </rdfs:subClassOf>')
            lines.append('    </rdf:Description>')
            lines.append('')

    # Disjoint axioms
    for c1, c2 in disjoints:
        lines.append('    <rdf:Description rdf:about="' + ns + '#' + c1 + '">')
        lines.append('        <owl:disjointWith rdf:resource="' + ns + '#' + c2 + '"/>')
        lines.append('    </rdf:Description>')
        lines.append('')

    lines.append('</rdf:RDF>')

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def main():
    os.makedirs("/app/data", exist_ok=True)

    generate_owl(
        SOURCE_CLASSES, SOURCE_OBJ_PROPS, SOURCE_DATA_PROPS, SOURCE_DISJOINTS,
        SOURCE_NS, "Retail Products Classification",
        "A hierarchical classification scheme for retail consumer products organized by product category",
        "/app/data/source_ontology.owl",
        aux_classes=SOURCE_AUX_CLASSES,
        equiv_classes=SOURCE_EQUIV_CLASSES,
        restrictions=SOURCE_RESTRICTIONS,
    )

    generate_owl(
        TARGET_CLASSES, TARGET_OBJ_PROPS, TARGET_DATA_PROPS, TARGET_DISJOINTS,
        TARGET_NS, "Industrial Supply Classification",
        "A hierarchical classification scheme for industrial and commercial supply chain products",
        "/app/data/target_ontology.owl",
        aux_classes=TARGET_AUX_CLASSES,
        equiv_classes=TARGET_EQUIV_CLASSES,
        restrictions=TARGET_RESTRICTIONS,
    )

    with open("/app/data/reference_sample.csv", 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(["source_id", "target_id", "relation"])
        for src, tgt, rel in REFERENCE_SAMPLE:
            w.writerow([src, tgt, rel])

    with open("/app/data/candidate_pairs.csv", 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(["source_id", "target_id"])
        for src, tgt in CANDIDATE_PAIRS:
            w.writerow([src, tgt])

    with open("/app/data/README.txt", 'w') as f:
        f.write("Ontology Alignment Task\n")
        f.write("=======================\n\n")
        f.write("This directory contains data for a multi-type ontology alignment task.\n\n")
        f.write("Files:\n")
        f.write("  source_ontology.owl  - Source product classification (OWL/RDF-XML format)\n")
        f.write("  target_ontology.owl  - Target product classification (OWL/RDF-XML format)\n")
        f.write("  reference_sample.csv - Labeled sample of concept pair alignments (training data)\n")
        f.write("  candidate_pairs.csv  - All concept pairs to classify (your task)\n\n")
        f.write("OWL constructs present in the ontologies:\n")
        f.write("  - rdfs:label, skos:altLabel, rdfs:comment (lexical annotations)\n")
        f.write("  - rdfs:subClassOf (class hierarchy)\n")
        f.write("  - owl:disjointWith (disjoint class axioms)\n")
        f.write("  - owl:equivalentClass with owl:intersectionOf and owl:Restriction\n")
        f.write("  - owl:Restriction with owl:onProperty + owl:someValuesFrom\n")
        f.write("  - owl:ObjectProperty and owl:DatatypeProperty\n\n")
        f.write("Relation types (from reference_sample.csv):\n")
        f.write("  =  equivalence    - Concepts represent the same set of instances\n")
        f.write("  >  superclass_of  - Source concept is strictly broader than target\n")
        f.write("  <  subclass_of    - Source concept is strictly narrower than target\n")
        f.write("  ~  overlap        - Concepts share some but not all instances\n")
        f.write("  !  disjoint       - Concepts share no instances\n\n")
        f.write("Ontology namespaces:\n")
        f.write("  Source: http://example.org/retailprod#\n")
        f.write("  Target: http://example.org/industrialsupply#\n\n")
        f.write("Output format:\n")
        f.write("  Write /app/alignment_output.csv with columns: source_id,target_id,relation\n")
        f.write("  Each row must classify one candidate pair from candidate_pairs.csv.\n")


if __name__ == "__main__":
    main()
