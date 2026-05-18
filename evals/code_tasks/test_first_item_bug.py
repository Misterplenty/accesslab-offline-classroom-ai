from submission import first_item


def test_first_item_returns_start_of_list():
    assert first_item(["sun", "moon", "star"]) == "sun"
