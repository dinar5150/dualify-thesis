# Analyze the histogram of jolt differences.
#
# Return the product of the respective counts of 1-jolt and 3-jolt differences.
def compute_result(histo: HistogramOfDeltas) -> int:
    """Analyze the histogram of jolt differences.

    :return: the product of the respective counts of 1s and 3s differences
    """
    delta_1s = histo[1] if 1 in histo else 0
    delta_3s = histo[3] if 3 in histo else 0

    return delta_1s * delta_3s
