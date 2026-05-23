from honua_esri_assess import __version__


def test_version_is_defined() -> None:
    assert isinstance(__version__, str)
    assert __version__
