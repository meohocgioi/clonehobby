import sys

import tpclone


def test_data_dir_rules(tmp_path, monkeypatch):
    app = tmp_path / "app"; app.mkdir()
    home = tmp_path / "home"; home.mkdir()
    monkeypatch.chdir(app)
    monkeypatch.setenv("HOME", str(home)); monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(home / "AppData"))
    monkeypatch.delenv("DB_PATH", raising=False); monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    # new install: per-user folder, NOT inside the unzipped app folder (so re-downloading can't lose it)
    (app / "data").mkdir()                                   # the empty data/ folder that ships in the ZIP
    d = tpclone.default_data_dir()
    assert app not in d.parents and str(home) in str(d)

    # older install that already has its ledger there keeps using it
    (app / "data" / "tpclone.db").write_bytes(b"x")
    assert tpclone.default_data_dir() == app / "data"

    # Docker / explicit path always wins
    monkeypatch.setenv("DB_PATH", str(tmp_path / "vol" / "tpclone.db"))
    assert tpclone.default_data_dir() == tmp_path / "vol"
    assert tpclone.overlay_root() == tmp_path / "vol" / "code"
