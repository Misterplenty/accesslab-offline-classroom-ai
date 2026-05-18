from submission import count_letters


def test_count_letters_counts_all_characters():
    assert count_letters("pear") == 4


def test_count_letters_handles_one_character():
    assert count_letters("a") == 1
