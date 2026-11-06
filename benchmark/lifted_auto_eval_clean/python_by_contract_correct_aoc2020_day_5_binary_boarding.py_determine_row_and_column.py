# Compute the ``(row, column)`` of the seat identified by the ``identifier``.
def determine_row_and_column(identifier: str) -> Tuple[int, int]:
    """Compute the ``(row, column)`` of the seat identified by the ``identifier``."""
    row_identifier = identifier[:7]
    column_identifier = identifier[7:]
    row = determine_row(identifier=row_identifier)
    column = determine_column(identifier=column_identifier)
    return row, column
