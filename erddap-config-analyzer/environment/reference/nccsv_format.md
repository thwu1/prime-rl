# NCCSV (NetCDF Comma Separated Values) Metadata Format

NCCSV is ERDDAP's format for representing NetCDF metadata as CSV text. It encodes variable attributes and global attributes in a structured, line-oriented format.

## Structure

Each line in the metadata section has the format:
```
<variable_name>,<attribute_name>,<value>
```

## Special Markers

| Marker | Meaning |
|--------|---------|
| `*GLOBAL*` | Variable name for global/dataset-level attributes |
| `*DATA_TYPE*` | Attribute name indicating a variable's data type |
| `*END_METADATA*` | Marks the end of the metadata section |

## Ordering Rules

1. **Global attributes** (`*GLOBAL*` entries) come first, in alphabetical order by attribute name.
2. **Axis variables** next, in dimension order (e.g., time, altitude, latitude, longitude).
3. **Data variables** last, in alphabetical order by variable name.
4. Within each variable, the `*DATA_TYPE*` line comes first, then attributes in **alphabetical order** by attribute name.

## Data Type Values

| NCCSV type | OPeNDAP type | NetCDF type |
|------------|-------------|-------------|
| `float`    | `Float32`   | `float`     |
| `double`   | `Float64`   | `double`    |
| `short`    | `Int16`     | `short`     |
| `int`      | `Int32`     | `int`       |
| `byte`     | `Byte`      | `byte`      |
| `String`   | `String`    | `char`/`string` |

## Quoting

- String values containing commas must be enclosed in double quotes.
- Values without commas may omit quotes.

## Example

```
*GLOBAL*,Conventions,"COARDS, CF-1.6, ACDD-1.3"
*GLOBAL*,institution,NOAA NMFS SWFSC ERD
*GLOBAL*,title,My Dataset Title
time,*DATA_TYPE*,double
time,axis,T
time,standard_name,time
time,units,"seconds since 1970-01-01T00:00:00Z"
latitude,*DATA_TYPE*,double
latitude,axis,Y
latitude,standard_name,latitude
latitude,units,degrees_north
sst,*DATA_TYPE*,float
sst,long_name,Sea Surface Temperature
sst,standard_name,sea_surface_temperature
sst,units,degree_C
*END_METADATA*
```

## Notes

- Use **source variable names** (the names from the OPeNDAP server / source file), not ERDDAP destination names.
- Include all attributes from the source DAS, including `_FillValue` and `actual_range`.
- Attributes starting with `_Coordinate` (ERDDAP internal) should be excluded.
