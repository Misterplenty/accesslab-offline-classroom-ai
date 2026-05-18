from submission import total_scores


def test_total_scores_adds_list_values():
    assert total_scores([2, 4, 6]) == 12


def test_total_scores_empty_list():
    assert total_scores([]) == 0
