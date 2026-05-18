from submission import average


def test_average_of_three_numbers():
    assert average([2, 4, 6]) == 4


def test_average_of_two_numbers():
    assert average([10, 14]) == 12
