"""Where govdiff decides the archive lives.

Day 4 shipped a defect: `repo_root()` walks two directories up from the module,
which is right in a clone and points into site-packages in a wheel install, so
`pip install govdiff` followed by `govdiff status` looked for `feeds.yaml`
inside the installed package. `resolve_repo_root()` is the fix, and these tests
pin all four of its branches.
"""

import pytest

from govdiff.cli import main
from govdiff.config import repo_root, resolve_repo_root
from govdiff.errors import RepoNotFound

FEEDS_YAML = """\
feeds:
  - id: demo
    name: Demo table
    country: BR
    publisher: Demo publisher
    enabled: false
    listing_url: null
    document_url: "http://example.invalid/doc.xlsx"
    format: xlsx
    parser: null
    key_fields: [code]
"""


def _checkout(path, name):
    root = path / name
    root.mkdir(parents=True, exist_ok=True)
    (root / "feeds.yaml").write_text(FEEDS_YAML, encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def _no_inherited_env(monkeypatch):
    monkeypatch.delenv("GOVDIFF_REPO", raising=False)
    monkeypatch.delenv("GOVDIFF_ROOT", raising=False)


# 1. --repo wins over everything.


def test_explicit_repo_wins_over_env_and_cwd(tmp_path, monkeypatch):
    wanted = _checkout(tmp_path, "wanted")
    other = _checkout(tmp_path, "other")
    elsewhere = _checkout(tmp_path, "elsewhere")
    monkeypatch.setenv("GOVDIFF_REPO", str(other))
    monkeypatch.chdir(elsewhere)
    assert resolve_repo_root(str(wanted)) == wanted.resolve()


def test_explicit_repo_without_feeds_yaml_is_an_error(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(RepoNotFound) as raised:
        resolve_repo_root(str(empty))
    assert "feeds.yaml" in str(raised.value)


# 2. GOVDIFF_REPO is next.


def test_env_repo_is_used_when_no_flag_is_given(tmp_path, monkeypatch):
    root = _checkout(tmp_path, "from-env")
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv("GOVDIFF_REPO", str(root))
    monkeypatch.chdir(outside)
    assert resolve_repo_root() == root.resolve()


def test_env_repo_pointing_nowhere_is_an_error_not_a_silent_fallback(tmp_path, monkeypatch):
    cwd = _checkout(tmp_path, "a-real-checkout")
    monkeypatch.setenv("GOVDIFF_REPO", str(tmp_path / "gone"))
    monkeypatch.chdir(cwd)
    with pytest.raises(RepoNotFound) as raised:
        resolve_repo_root()
    assert "GOVDIFF_REPO" in str(raised.value)


def test_govdiff_root_still_works_as_an_alias(tmp_path, monkeypatch):
    root = _checkout(tmp_path, "legacy")
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv("GOVDIFF_ROOT", str(root))
    monkeypatch.chdir(outside)
    assert resolve_repo_root() == root.resolve()


# 3. The working directory, when it is a checkout.


def test_cwd_is_used_when_it_holds_feeds_yaml(tmp_path, monkeypatch):
    root = _checkout(tmp_path, "cwd-checkout")
    monkeypatch.chdir(root)
    assert resolve_repo_root() == root.resolve()


# 4. Otherwise: a message that says what to do.


def test_a_directory_that_is_not_a_checkout_gets_a_clear_error(tmp_path, monkeypatch):
    outside = tmp_path / "somewhere-else"
    outside.mkdir()
    monkeypatch.chdir(outside)
    with pytest.raises(RepoNotFound) as raised:
        resolve_repo_root()
    message = str(raised.value)
    assert "git clone" in message
    assert "--repo" in message
    assert "GOVDIFF_REPO" in message
    assert str(outside.resolve()) in message


def test_the_package_directory_is_not_a_fallback(tmp_path, monkeypatch):
    """The wheel-install defect itself: site-packages must never be the answer."""
    outside = tmp_path / "not-a-checkout"
    outside.mkdir()
    monkeypatch.chdir(outside)
    with pytest.raises(RepoNotFound):
        resolve_repo_root()
    # repo_root() is untouched and still answers the source-tree question.
    assert (repo_root() / "feeds.yaml").exists()


# The CLI carries both spellings through to the resolver.


def test_cli_accepts_repo_and_root_for_the_same_thing(tmp_path, capsys):
    root = _checkout(tmp_path, "cli-checkout")
    assert main(["--repo", str(root), "status"]) == 0
    first = capsys.readouterr().out
    assert main(["--root", str(root), "status"]) == 0
    assert capsys.readouterr().out == first
    assert "demo" in first


def test_cli_reports_the_missing_archive_instead_of_crashing(tmp_path, monkeypatch, capsys):
    outside = tmp_path / "bare"
    outside.mkdir()
    monkeypatch.chdir(outside)
    assert main(["status"]) == 1
    assert "no archive found" in capsys.readouterr().err
