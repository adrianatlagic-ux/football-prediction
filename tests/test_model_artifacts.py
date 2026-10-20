import hashlib
import json
import pytest
from scripts.verify_models import verify_files


def fixture_models(tmp_path):
    models = {}
    for name in ["club_model_v3.joblib", "model.joblib"]:
        content = b"test artifact"
        (tmp_path / name).write_bytes(content)
        models[name] = {"size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    (tmp_path / "model-manifest.json").write_text(json.dumps({"models": models}))
    return tmp_path


def test_valid_checksums(tmp_path):
    verify_files(fixture_models(tmp_path))


@pytest.mark.parametrize("failure", ["missing", "pointer", "corrupted"])
def test_rejects_unusable_artifacts(tmp_path, failure):
    root = fixture_models(tmp_path)
    path = root / "model.joblib"
    if failure == "missing":
        path.unlink()
    elif failure == "pointer":
        path.write_text("version https://git-lfs.github.com/spec/v1\n")
    else:
        path.write_bytes(b"fake artifact")
    with pytest.raises(ValueError):
        verify_files(root)
