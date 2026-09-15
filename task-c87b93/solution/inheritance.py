"""CSS property inheritance through the DOM tree."""

INHERITED_PROPERTIES = frozenset({
    'azimuth', 'border-collapse', 'border-spacing', 'caption-side',
    'color', 'cursor', 'direction', 'empty-cells',
    'font', 'font-family', 'font-size', 'font-style', 'font-variant',
    'font-weight', 'letter-spacing', 'line-height', 'list-style',
    'list-style-image', 'list-style-position', 'list-style-type',
    'orphans', 'quotes', 'text-align', 'text-indent', 'text-transform',
    'visibility', 'white-space', 'widows', 'word-spacing',
})


def is_inherited_property(prop):
    """Return True if *prop* inherits by default (includes custom --* props)."""
    return prop.startswith('--') or prop in INHERITED_PROPERTIES


def apply_inheritance(element, raw_cascade, parent_computed):
    """Merge cascade result with inherited values for *element*.

    Parameters
    ----------
    element : DOMNode
    raw_cascade : dict
        ``{path: {prop: value}}`` from the flat cascade pass.
    parent_computed : dict
        Fully-resolved property dict of the parent element.

    Returns
    -------
    dict
        Merged property dict for this element (before var/calc resolution).
    """
    path = element.full_path()
    my_props = dict(raw_cascade.get(path, {}))

    # Track properties explicitly set to 'initial' so they block inheritance
    initial_props = set()

    for prop, val in list(my_props.items()):
        if val == 'inherit':
            inherited = parent_computed.get(prop)
            if inherited is not None:
                my_props[prop] = inherited
            else:
                del my_props[prop]
        elif val == 'initial':
            del my_props[prop]
            initial_props.add(prop)

    # Implicit inheritance for inherited properties
    if parent_computed:
        for prop, val in parent_computed.items():
            if (prop not in my_props
                    and prop not in initial_props
                    and is_inherited_property(prop)
                    and val is not None):
                my_props[prop] = val

    return my_props
