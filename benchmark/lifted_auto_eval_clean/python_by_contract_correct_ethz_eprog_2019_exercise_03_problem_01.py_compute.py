# Compute the recursive sum ``s = 1 / (1**2) + 1 / (2**2) + … + 1 / (n**2)``.
#
#
#   >>> compute(0)
#
#   0
#
#
#   >>> compute(4)
#
#   1.4236111111111112
def compute(n: int) -> float:
    """
    Compute the recursive sum ``s = 1 / (1**2) + 1 / (2**2) + … + 1 / (n**2)``.

    >>> compute(0)
    0

    >>> compute(4)
    1.4236111111111112
    """
    if n == 0:
        return 0

    return sum(1 / (i**2) for i in range(1, n + 1))
