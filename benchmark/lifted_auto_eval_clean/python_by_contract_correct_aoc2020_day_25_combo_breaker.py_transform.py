# Transform the ``subject`` in ``loop_size`` steps of a hard-coded algorithm.
def transform(subject: int, loop_size: int) -> int:
    """Transform the ``subject`` in ``loop_size`` steps of a hard-coded algorithm."""
    value = 1
    for _ in range(loop_size):
        value *= subject
        value %= 20201227
    return value
