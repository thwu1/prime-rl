"""CF (Climate and Forecast) data model reference.

Defines the conceptual structures used in CF-compliant climate data files.
This module is for reference only - the pipeline works with raw JSON data
structures that follow these conventions.

Do not modify this file.
"""


class Bounds:
    """Represents coordinate bounds (cell edges).

    For a dimension coordinate with N values, bounds is an N x 2 array
    where bounds[i] = [lower_edge, upper_edge] for cell i.
    """

    def __init__(self, data):
        self.data = data

    def __len__(self):
        return len(self.data)


class DimensionCoordinate:
    """A CF dimension coordinate with values, bounds, units, and optional calendar.

    Attributes:
        units: coordinate units (e.g., 'days since 2003-01-01', 'degrees_north')
        calendar: CF calendar type for time coordinates
                  ('standard', '360_day', 'noleap', etc.)
        bounds: Bounds object defining cell edges
    """

    def __init__(self, units, bounds=None, calendar=None):
        self.units = units
        self.bounds = bounds
        self.calendar = calendar


class CellMethod:
    """A CF cell method describing a statistical operation applied to data.

    CF cell_methods strings track the chain of operations used to derive data.
    Format: "axes: method (qualifier: value)"

    Examples:
        "time: mean (within: years)"
        "time: mean (over: years)"
        "area: mean"

    A climatological mean chain:
        "time: mean (within: years) time: mean (over: years) area: mean"

    This encodes that data was first averaged within each year (weighted by
    time intervals), then averaged over years, then spatially averaged.
    """

    def __init__(self, axes, method, qualifiers=None):
        self.axes = axes
        self.method = method
        self.qualifiers = qualifiers or {}


class Field:
    """A CF field construct: data array with coordinate metadata.

    A field has:
        - An N-dimensional data array
        - Dimension coordinates (time, latitude, longitude, etc.)
        - Properties (standard_name, units, etc.)
        - Cell methods tracking statistical provenance

    The data ordering convention is: data[time][latitude][longitude].

    For climatological processing, the key metadata elements are:
        - time coordinate bounds (defining month durations)
        - time coordinate calendar (standard, 360_day, noleap, etc.)
        - latitude/longitude bounds (defining grid cell edges)
        - reference_year (base year for time index to date conversion)
    """

    def __init__(self, data, coordinates, properties=None):
        self.data = data
        self.coordinates = coordinates
        self.properties = properties or {}
