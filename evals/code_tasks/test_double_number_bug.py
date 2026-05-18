from submission import double_number


def test_double_number_positive():
    assert double_number(3) == 6


def test_double_number_zero():
    assert double_number(0) == 0
