"""Hierarchical land cover taxonomy based on LandCoverNet."""

CLASSES_L3 = ["Snow/Ice", "Water", "Artificial", "Natural",
              "Woody", "Cultivated", "Semi-Natural"]

CLASSES_L2 = ["Snow/Ice", "Water", "Bare Ground", "Woody", "Non-Woody"]

CLASSES_L1 = ["Bare", "Vegetation"]

L3_TO_L2 = {0: 0, 1: 1, 2: 2, 3: 2, 4: 3, 5: 4, 6: 4}

L3_TO_L1 = {0: 0, 1: 0, 2: 0, 3: 0, 4: 1, 5: 1, 6: 1}


def get_classes(level):
    if level == 3:
        return CLASSES_L3
    elif level == 2:
        return CLASSES_L2
    elif level == 1:
        return CLASSES_L1
    raise ValueError(f"Invalid level: {level}")


def get_mapping(level):
    if level == 3:
        return {i: i for i in range(7)}
    elif level == 2:
        return L3_TO_L2
    elif level == 1:
        return L3_TO_L1
    raise ValueError(f"Invalid level: {level}")
