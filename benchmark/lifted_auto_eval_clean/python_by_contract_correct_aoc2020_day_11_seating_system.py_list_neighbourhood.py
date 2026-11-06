# List all the neighbours of the given seat at position ``i, j``.
#
# The ``height`` and ``width`` define the limits of the layout.
def list_neighbourhood(
    i: int, j: int, height: int, width: int
) -> List[Tuple[int, int]]:
    """
    List all the neighbours of the given seat at position ``i, j``.

    The ``height`` and ``width`` define the limits of the layout.
    """
    # (mristin, 2021-04-03): This would be a nice use case for ensure_each.
    start_i = max(0, i - 1)
    end_i = min(height, i + 2)
    start_j = max(0, j - 1)
    end_j = min(width, j + 2)

    result = []  # type: List[Tuple[int, int]]
    for neighbour_i in range(start_i, end_i):
        for neighbour_j in range(start_j, end_j):
            if neighbour_i == i and neighbour_j == j:
                continue

            result.append((neighbour_i, neighbour_j))

    return result
