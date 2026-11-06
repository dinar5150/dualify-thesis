# Count the trees in the ``input_string``.
def count_trees(width: int, height: int, input_string: str) -> int:
    """Count the trees in the ``input_string``."""
    count: int = 0
    current_x: int = 0
    current_y: int = 0

    while current_y < height:
        if input_string[current_y * width + current_x] == "#":
            count += 1
        current_x = (current_x + STEP_SIZE_HORIZONTAL) % width
        current_y += STEP_SIZE_VERTICAL

    return count
