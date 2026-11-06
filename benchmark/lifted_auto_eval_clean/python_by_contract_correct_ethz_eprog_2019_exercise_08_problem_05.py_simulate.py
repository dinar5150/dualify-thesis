# Simulate ``trials`` number of wolf journeys on the quadratic ``grid_size`` grid.
def simulate(trials: int, grid_size: int) -> float:
    """
    Simulate ``trials` number of wolf journeys on the quadratic ``grid_size`` grid."""
    success_count = 0

    half_grid_size = grid_size // 2
    border = (-half_grid_size, half_grid_size)

    for _ in range(trials):
        visited = set()  # type: Set[Position]

        position = Position(x=0, y=0)

        success = None  # type: Optional[bool]
        while True:
            assert position.x < half_grid_size, (
                f"position invariant for x: "
                f"{position=}, {half_grid_size=}, {grid_size=}"
            )
            assert position.y < half_grid_size, (
                f"position invariant for y: "
                f"{position=}, {half_grid_size=}, {grid_size=}"
            )
            assert (
                position not in visited
            ), f"visited invariant: {visited=}, {grid_size=}"

            old_visited_len = len(visited)
            visited.add(position)

            next_positions = list_next_positions(pos=position)

            if all(next_pos in visited for next_pos in next_positions):
                success = False
                break

            position = random.choice(
                [pos for pos in next_positions if pos not in visited]
            )
            if position.x in border or position.y in border:
                success = True
                break

            assert len(visited) == old_visited_len + 1, "Loop invariant"

        assert success is not None

        if success:
            success_count += 1

    return success_count / trials
