# Behavior of compute_grade
def compute_grade(homework_scores: List[float], exam_scores: List[float]) -> float:
    # Make exams matter more by counting them twice:
    all_scores = homework_scores + exam_scores + exam_scores
    return sum(all_scores) / len(all_scores)
