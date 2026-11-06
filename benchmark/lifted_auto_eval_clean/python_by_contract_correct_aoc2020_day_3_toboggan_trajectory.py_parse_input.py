# Parse the input map given as ``lines`` into width, height, and the flattened map string.
def parse_input(lines: List[str]) -> Tuple[int, int, str]:
    """Parse the input map given as ``lines``."""
    width: int = len(lines[0])
    height: int = len(lines)
    return width, height, "".join(lines)
