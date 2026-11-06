# Verify the ``password`` under the given constraints.
def verify(min_count: int, max_count: int, character: str, password: str) -> bool:
    """Verify the ``password`` under the given constraints."""
    # crosshair: on
    answer = min_count <= password.count(character) <= max_count
    return answer
