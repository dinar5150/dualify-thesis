# Compute the row of the seat identified by ``identifier``.
def determine_row(identifier: str) -> int:
    """Compute the row of the seat identified by the ``identifier``."""
    first = 0
    last = 127

    for directive in identifier:
        first, last = apply(first=first, last=last, directive=directive)

    assert first == last, "The last step should have completely defined the row."
    return first
