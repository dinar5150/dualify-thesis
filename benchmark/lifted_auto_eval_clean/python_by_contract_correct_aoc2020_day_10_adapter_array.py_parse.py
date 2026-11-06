# Parse the specification of the adapters given as lines.
#
# Return a list of corresponding adapter jolt values.
def parse(lines: Lines) -> List[int]:
    """
    Parse the specification of the adapters given as ``lines``.

    :return: List of corresponding number of adapter jolts
    """
    return [int(line) for line in lines]
