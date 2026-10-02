import pytest

from absencegate import season


@pytest.fixture(scope="session")
def season_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("season")
    code, text = season.run(root / "data", root / "runs")
    return root, code, text
