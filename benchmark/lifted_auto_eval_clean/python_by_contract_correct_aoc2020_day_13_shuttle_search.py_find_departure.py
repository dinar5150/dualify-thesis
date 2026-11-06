# Find the earliest bus to catch after ``start_time``.
def find_departure(start_time: int, bus_ids: Set[int]) -> Tuple[int, int]:
    """Find the earliest bus to catch after ``start_time``."""
    return min([(next_departure(bid, start_time), bid) for bid in bus_ids])
