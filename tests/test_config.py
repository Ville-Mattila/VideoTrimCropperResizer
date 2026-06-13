def test_config_roundtrip(leike, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    leike["save_config"]({"fmt": "GIF", "crf": 18, "out_dir": "C:/clips"})
    assert leike["load_config"]() == {"fmt": "GIF", "crf": 18, "out_dir": "C:/clips"}


def test_config_missing_is_empty(leike, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "does_not_exist"))
    assert leike["load_config"]() == {}
