from types import SimpleNamespace

from utils.formatting import format_duration, format_user


def test_format_duration_zero_and_negative():
    assert format_duration(0) == "00:00"
    assert format_duration(-5) == "00:00"


def test_format_duration_minutes():
    assert format_duration(65) == "01:05"
    assert format_duration(599) == "09:59"


def test_format_duration_hours():
    assert format_duration(3661) == "1:01:01"
    assert format_duration(7200) == "2:00:00"


def test_format_user_no_discriminator():
    user = SimpleNamespace(display_name="Bob", name="bob123")
    assert format_user(user) == "Bob (@bob123)"
