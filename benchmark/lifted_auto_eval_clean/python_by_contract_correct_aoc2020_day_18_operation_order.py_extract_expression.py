# Extract the sub-expression surrounded by parentheses in ``expr``.
def extract_expression(expr: str) -> str:
    """Extract the sub-expression surrounded by parentheses in ``expr``."""
    parenthesis_balance = 0
    result = ""

    for c in expr:
        if c == "(":
            parenthesis_balance += 1
        elif c == ")":
            parenthesis_balance -= 1

        if parenthesis_balance == 0:
            return result[1:]
        else:
            result += c
    raise Exception("I should never end up here!")
