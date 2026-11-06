# Compute the score for the given deck by summing each card multiplied by its positional weight: for index i, the card contributes (len(deck) - i) * deck[i]. Return the total as an integer.
def compute_score(deck: Deck) -> int:
    """Compute the score for the given deck based on its cards."""
    score = 0
    for i, card in enumerate(deck):
        score += (len(deck) - i) * card

    return score
