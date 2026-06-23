from utils.validation import is_http_url


def test_valid_urls():
    assert is_http_url("https://example.com/image.png")
    assert is_http_url("http://a.b")


def test_invalid_urls():
    assert not is_http_url(None)
    assert not is_http_url("")
    assert not is_http_url("ftp://example.com")
    assert not is_http_url("not a url")
    assert not is_http_url("javascript:alert(1)")
