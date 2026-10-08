"""CC-212: the exhaustion path — a test no change to src/ can make pass."""


def test_unfixable():
    assert False  # intentional: this test can never pass — CC-212
