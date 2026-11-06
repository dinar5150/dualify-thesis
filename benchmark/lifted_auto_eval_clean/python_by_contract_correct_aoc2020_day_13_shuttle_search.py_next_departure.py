# Compute the next departure of ``bus_id`` leaving earliest at ``min_time``.
def next_departure(bus_id: int, min_time: int) -> int:
    """Compute the next departure of ``bus_id`` leaving earliest at ``min_time``."""
    missed_last_bus_by = min_time % bus_id
    if missed_last_bus_by == 0:
        return min_time
    else:
        return min_time - missed_last_bus_by + bus_id
