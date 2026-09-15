# HL7 v2 Conformance Profile XML Schema Reference

## Root Element: `<ConformanceProfile>`

Attributes: `ID`, `Type`, `HL7Version`, `SchemaVersion`

## `<Messages>` / `<Message>`

Each `<Message>` has attributes: `ID`, `Type`, `Event`, `StructID`, `Description`

Children are an ordered sequence of `<Segment>` references and `<Group>` elements defining the expected message structure.

### `<Segment>` (within Message)
Attributes:
- `Ref`: references a segment ID defined in `<Segments>`
- `Usage`: R (Required), RE (Required but may be Empty), O (Optional), X (Forbidden/Not supported), W (Withdrawn), C (Conditional), B (Backward compatible)
- `Min`: minimum occurrences (integer)
- `Max`: maximum occurrences (integer or `*` for unbounded)

### `<Group>`
Attributes: `ID`, `Name`, `Usage`, `Min`, `Max`
Children: ordered sequence of `<Segment>` and nested `<Group>` elements.

## `<Segments>` / `<Segment>`

Each `<Segment>` defines the fields within a segment type.
Attributes: `ID`, `Label`, `Name`, `Description`
Children: ordered list of `<Field>` elements.

### `<Field>`
Attributes:
- `Name`: human-readable field name
- `Datatype`: references a datatype ID from `<Datatypes>`, or `-` for withdrawn
- `Usage`: R/RE/O/X/W/C/B
- `Min`: minimum repetitions
- `Max`: maximum repetitions (integer or `*`)
- `MinLength`: minimum character length of the value
- `MaxLength`: maximum character length (integer or `*` for unbounded)
- `ItemNo`: HL7 item number

## `<Datatypes>` / `<Datatype>`

Each `<Datatype>` has attributes: `ID`, `Name`, `Description`
- Primitive datatypes have no children
- Composite datatypes contain ordered `<Component>` elements

### `<Component>`
Attributes:
- `Name`: component name
- `Datatype`: references another datatype ID
- `Usage`: R/RE/O/X/W/C/B
- `MinLength`, `MaxLength`, `ConfLength`: length constraints

## ER7 Encoding Rules

- MSH-1 (character at position 3) defines the field separator (typically `|`)
- MSH-2 (next 4-5 characters) defines encoding characters: component separator (typically `^`), repetition separator (`~`), escape character (`\`), subcomponent separator (`&`), optionally truncation character (`#`)
- Fields are separated by the field separator
- Repetitions of a field are separated by the repetition separator
- Components within a composite field are separated by the component separator
- Subcomponents are separated by the subcomponent separator
- Escape sequences: `\F\` = field sep, `\S\` = component sep, `\R\` = repetition sep, `\E\` = escape char, `\T\` = subcomponent sep
