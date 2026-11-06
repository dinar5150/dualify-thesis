# Compute the column of the seat identified by the ``identifier``.
def determine_column(identifier: str) -> int:
    """Compute the column of the seat identified by the ``identifier``."""
    first = 0
    last = 7

    for directive in identifier:
        first, last = apply(first=first, last=last, directive=directive)

    assert first == last, "The last step should have completely defined the column."
    return first
