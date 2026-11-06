def _assert_double_swap_does_nothing(things: Tuple[int, int]) -> Tuple[int, int]:
    """
    Return the input tuple unchanged after applying swap twice.

    """
    once = (things[1], things[0])
    return (once[1], once[0])
