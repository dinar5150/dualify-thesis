# Return a list of the first N even Fibonacci numbers.
#
# >>> even_fibb(2)
# [2, 8]
def even_fibb(n: int) -> List[int]:
    """
    Return a list of the first N even fibbonacci numbers.

    >>> even_fibb(2)
    [2, 8]
    """
    prev = 1
    cur = 1
    result = []
    while n > 0:
        prev, cur = cur, prev + cur
        if cur % 2 == 0:
            result.append(cur)
            n -= 1
    return result
