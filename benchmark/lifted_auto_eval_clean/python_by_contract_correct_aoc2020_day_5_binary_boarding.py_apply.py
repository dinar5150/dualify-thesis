# Apply the ``directive`` given the range as ``[first, last]`` (inclusive).
def apply(first: int, last: int, directive: str) -> Tuple[int, int]:
    """
    Apply the ``directive`` given the range as ``[first, last]`` (inclusive).

    :return: new first, new last
    """
    half = int((last - first + 1) / 2)

    if directive in "FL":
        return first, last - half

    elif directive in "BR":
        return first + half, last

    else:
        raise NotImplementedError(directive)
