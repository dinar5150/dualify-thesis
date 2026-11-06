# Find the two entries in items that sum to total. Return them as a tuple (x, y) where x appears at an earlier position than y in items, or return None if no such pair exists.
def find_pair_with_sum(items: List[int], total: int) -> Optional[Tuple[int, int]]:
    """Find the two entries that sum to ``total``."""
    for i, x in enumerate(items):
        for y in items[i + 1 :]:
            if x + y == total:
                return (x, y)
    return None
