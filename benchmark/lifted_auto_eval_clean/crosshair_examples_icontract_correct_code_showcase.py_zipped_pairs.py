# Behavior of zipped_pairs
def zipped_pairs(x: List[T]) -> List[Tuple[T, T]]:
    return zip_exact(x[:-1], x[1:])
