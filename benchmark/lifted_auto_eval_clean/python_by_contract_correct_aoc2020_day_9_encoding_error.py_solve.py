# Parse the data of the XMAS protocol, ``puzzle_input``, and find a weakness.
#
# :return:
#     offset of the number,
#     first number *after* the preamble which uncovers the weakness
def solve(puzzle_input: List[int], preamble_length: int) -> Optional[Tuple[int, int]]:
    """
    Parse the data of the XMAS protocol, ``puzzle_input``, and find a weakness.

    :return:
        offset of the number,
        first number *after* the preamble which uncovers the weakness
    """
    for index, number in enumerate(puzzle_input[preamble_length:]):
        preamble = puzzle_input[index : index + preamble_length]
        valid = False
        for i in preamble:
            for j in preamble:
                if i != j and i + j == number:
                    valid = True
        if not valid:
            return preamble_length + index, number

    return None
