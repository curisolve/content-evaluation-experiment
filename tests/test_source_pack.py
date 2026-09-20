import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
capture = importlib.import_module("capture_cmto")
verify = importlib.import_module("verify_cmto_pack").verify


def test_normalization() -> None:
    raw = b"<h1>Title</h1><script>secret</script><p>A &amp;  B</p>"
    assert capture.normalize(raw) == "Title\nA & B\n"


@pytest.mark.parametrize("tamper", [None, "raw", "normalized", "escape", "version"])
def test_integrity(tmp_path: Path, tamper: str | None) -> None:
    raw = b"<p>Example</p>"
    normalized = capture.normalize(raw).encode()
    (tmp_path / "source.html").write_bytes(raw)
    (tmp_path / "source.txt").write_bytes(normalized)
    source = {
        "id": "example",
        "raw_path": "source.html",
        "normalized_path": "source.txt",
        "byte_length": len(raw),
        "raw_sha256": capture.sha256(raw),
        "normalized_sha256": capture.sha256(normalized),
        "normalization_version": "visible-text-v1",
    }
    if tamper == "raw":
        (tmp_path / "source.html").write_bytes(b"changed")
    elif tamper == "normalized":
        (tmp_path / "source.txt").write_bytes(b"changed")
    elif tamper == "escape":
        source["raw_path"] = "../outside.html"
    elif tamper == "version":
        source["normalization_version"] = "future"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"sources": [source]}))
    if tamper:
        with pytest.raises(ValueError):
            verify(manifest, tmp_path)
    else:
        assert verify(manifest, tmp_path) == 1


def test_capture_refuses_existing_directory(tmp_path: Path) -> None:
    with pytest.raises(FileExistsError):
        capture.capture(tmp_path)


def test_pack_references_and_allocations() -> None:
    path = ROOT / "subjects/cmto_consent_boundaries_v1.json"
    subject = json.loads(path.read_text())
    for key in ("source_pack", "rubric"):
        assert (path.parent / subject[key]).is_file()
    batch = subject["development_batch"]
    assert (
        sum(
            batch[key]
            for key in ("ordinary", "single_defect_mutations", "semantic_duplicate_variants")
        )
        == batch["total"]
    )
    for key in ("topic_marginals", "audience_marginals", "difficulty_marginals"):
        assert sum(batch[key].values()) == batch["total"]
    rubric = json.loads((path.parent / subject["rubric"]).read_text())
    assert len({check["id"] for check in rubric["checks"]}) == len(rubric["checks"])
