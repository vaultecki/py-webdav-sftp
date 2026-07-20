import pytest
from conftest import REMOTE_ROOT
from wsgidav.dav_error import DAVError


@pytest.mark.parametrize("dav_path,expected", [
    ("/foo/bar", f"{REMOTE_ROOT}/foo/bar"),
    ("/", REMOTE_ROOT),
    ("/foo/../bar", f"{REMOTE_ROOT}/bar"),  # bleibt innerhalb des Roots - erlaubt
])
def test_allowed_paths_resolve_inside_root(provider, dav_path, expected):
    assert provider._to_remote_path(dav_path) == expected


@pytest.mark.parametrize("dav_path", [
    "/../../etc/passwd",
    "/foo/../../../etc/shadow",
    "/..",
    "/../",
])
def test_traversal_attempts_are_blocked(provider, dav_path):
    with pytest.raises(DAVError):
        provider._to_remote_path(dav_path)
