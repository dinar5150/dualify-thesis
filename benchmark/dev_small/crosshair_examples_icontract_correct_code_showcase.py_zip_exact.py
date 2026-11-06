# Return the pairwise zip of two iterables that must have equal length; each output element pairs the k-th element of a with the k-th element of b, and the result length equals the common input length.
def zip_exact(a: Iterable[T], b: Iterable[U]) -> List[Tuple[T, U]]:
    return list(zip(a, b))
