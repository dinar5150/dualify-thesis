# Compute the identifier of the seat given its ``row`` and ``column``.
def determine_id(row: int, column: int) -> int:
    """Compute the identifier of the seat given its ``row`` and ``column``."""
    return row * 8 + column
