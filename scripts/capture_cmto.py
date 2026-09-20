"""Capture public CMTO sources locally; emit metadata without redistributing source text.

Run from the repository root with uv run python scripts/capture_cmto.py OUTPUT_DIRECTORY.
A new directory is required. The resulting manifest is content-addressed, not overwritten.
"""

import hashlib
import json
import sys
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import httpx

SOURCES = {
    "cmto_consent": "https://www.cmto.com/rules/standard-of-practice-consent/",
    "cmto_boundaries": "https://www.cmto.com/rules/standard-of-practice-professional-boundaries-draping-and-physical-privacy/",
    "cmto_effective_date": "https://www.cmto.com/all-touchpoints/standards-and-policy-consolidation-effective-september-8-2026/",
}


class VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        if tag in {"p", "li", "h1", "h2", "h3", "h4", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "li", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def normalize(raw: bytes) -> str:
    parser = VisibleText()
    parser.feed(raw.decode("utf-8"))
    return (
        "\n".join(
            cleaned
            for line in "".join(parser.parts).splitlines()
            if (cleaned := " ".join(line.split()))
        )
        + "\n"
    )


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def capture(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    records = []
    with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
        for source_id, url in SOURCES.items():
            response = client.get(url)
            response.raise_for_status()
            raw = response.content
            if "text/html" not in response.headers.get("content-type", ""):
                raise ValueError("expected an HTML source")
            normalized = normalize(raw).encode()
            (output / f"{source_id}.html").write_bytes(raw)
            (output / f"{source_id}.txt").write_bytes(normalized)
            records.append(
                {
                    "id": source_id,
                    "url": url,
                    "final_url": str(response.url),
                    "retrieved_at": datetime.now(UTC).isoformat(),
                    "http_status": response.status_code,
                    "response_headers": {
                        key: response.headers[key]
                        for key in (
                            "content-type",
                            "etag",
                            "last-modified",
                            "date",
                            "content-encoding",
                        )
                        if key in response.headers
                    },
                    "raw_path": f"{source_id}.html",
                    "normalized_path": f"{source_id}.txt",
                    "raw_sha256": sha256(raw),
                    "normalized_sha256": sha256(normalized),
                    "byte_length": len(raw),
                    "normalization_version": "visible-text-v1",
                }
            )
    manifest = {
        "schema_version": 1,
        "id": f"cmto_consent_boundaries_{datetime.now(UTC):%Y_%m_%d}",
        "status": "captured_for_development",
        "sources": records,
        "raw_byte_semantics": "HTTP entity bytes after content-encoding decompression",
        "normalization_scope": (
            "Whole-page visible text, including navigation; not a requirements-only extraction"
        ),
        "redistribution": "Not established; raw and normalized source artifacts stay out of Git",
    }
    (output / "capture.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    capture(Path(sys.argv[1]))
