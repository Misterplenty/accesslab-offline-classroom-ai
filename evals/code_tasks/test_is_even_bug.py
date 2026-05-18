from submission import is_even


def test_is_even_true_for_even_number():
    assert is_even(4) is True


def test_is_even_false_for_odd_number():
    assert is_even(5) is False
