# Compute the duration of the stay.
def duration(self_start: int, self_end: int) -> int:
    """Compute the duration of the stay."""
    return self_end - self_start + 1
