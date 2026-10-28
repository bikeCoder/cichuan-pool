"""共享夹具：临时数据根。"""
from __future__ import annotations

import pytest


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "poolroot"
    d.mkdir()
    return d
