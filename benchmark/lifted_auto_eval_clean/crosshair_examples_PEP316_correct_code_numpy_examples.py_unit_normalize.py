# Normalize the given array values into the [0,1] range.
#
# >>> unit_normalize(np.arange(-1, 2))
# array([0. , 0.5, 1. ])
def unit_normalize(a: np.ndarray) -> np.ndarray:
    """
    Normalize the given array values into the [0,1] range.

    >>> unit_normalize(np.arange(-1, 2))
    array([0. , 0.5, 1. ])

    """
    return (a - np.min(a)) / np.ptp(a)
