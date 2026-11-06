# Behavior of csv_first_column: for each line in `lines`, return the substring of the line up to (but not including) the first comma. Requires every line to contain at least one comma.
def csv_first_column(lines: List[str]) -> List[str]:
    return [line[: line.index(",")] for line in lines]
