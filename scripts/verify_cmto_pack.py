"""Offline integrity check; passing does not certify extraction or clinical correctness."""

import argparse
import json
from pathlib import Path

from capture_cmto import normalize, sha256


def verify(manifest_path: Path, artifact_root: Path) -> int:
    manifest = json.loads(manifest_path.read_text())
    sources = manifest["sources"]
    if not sources or len({source["id"] for source in sources}) != len(sources):
        raise ValueError("empty or duplicate source IDs")
    for source in sources:
        if source["normalization_version"] != "visible-text-v1":
            raise ValueError("unsupported normalization version")
        paths = []
        for key in ("raw_path", "normalized_path"):
            path = (artifact_root / source[key]).resolve()
            if not path.is_relative_to(artifact_root.resolve()):
                raise ValueError("artifact path escapes root")
            paths.append(path)
        raw, normalized = (path.read_bytes() for path in paths)
        if len(raw) != source["byte_length"] or sha256(raw) != source["raw_sha256"]:
            raise ValueError(f"raw artifact mismatch: {source['id']}")
        if sha256(normalized) != source["normalized_sha256"]:
            raise ValueError(f"normalized artifact mismatch: {source['id']}")
        if normalize(raw).encode() != normalized:
            raise ValueError(f"normalization mismatch: {source['id']}")
    return len(sources)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("artifact_root", type=Path)
    args = parser.parse_args()
    count = verify(args.manifest, args.artifact_root)
    print(f"Verified {count} source artifacts; content review remains a separate gate.")
