def test_mitmdump_available():
    """mitmdump must be available on PATH when vibedom is installed."""
    import shutil
    assert shutil.which('mitmdump') is not None, \
        "mitmdump not found — add mitmproxy to pyproject.toml dependencies"
