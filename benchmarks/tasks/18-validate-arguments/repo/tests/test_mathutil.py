from app.mathutil import average, repeat


def test_coerces_arguments():
    assert average(["1", 2]) == 1.5
    assert repeat("ab", "3") == "ababab"
