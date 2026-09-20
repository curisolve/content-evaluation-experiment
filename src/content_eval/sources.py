"""Verified local CMTO authority; extraction is deterministic, not clinical review."""

import hashlib
import json
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from content_eval.models import digest

EXTRACTION_VERSION = "cmto-article-v1"
EXPECTED_COUNTS = {"cmto_consent": 9, "cmto_boundaries": 19}
ALLOWED = {
    "cmto_consent": (1, 3, 8, 9),
    "cmto_boundaries": (3, 4, 5, 6, 7, 9, 10, 11, 12, 15, 16, 17, 18, 19),
}


@dataclass
class Node:
    tag: str
    attrs: dict[str, str | None] = field(default_factory=dict)
    children: list[Node | str] = field(default_factory=list)

    def text(self) -> str:
        return " ".join(
            " ".join(c.text() if isinstance(c, Node) else c for c in self.children).split()
        )

    def descendants(self, tag: str) -> list[Node]:
        result = []
        for child in self.children:
            if isinstance(child, Node):
                if child.tag == tag:
                    result.append(child)
                result.extend(child.descendants(tag))
        return result


class Tree(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def extract(raw: bytes, source_id: str) -> dict[str, Any]:
    tree = Tree()
    tree.feed(raw.decode("utf-8"))
    articles = [
        node
        for node in tree.root.descendants("div")
        if "left-col" in (node.attrs.get("class") or "").split()
        and any(h.text() == "Requirements" for h in node.descendants("h3"))
    ]
    if len(articles) != 1:
        raise ValueError("expected one requirements article")
    article = articles[0]
    requirements: dict[str, str] = {}
    context: list[str] = []
    active = False
    governing = ""
    next_number = 1
    for node in article.children:
        if not isinstance(node, Node):
            continue
        if node.tag == "h3" and node.text() == "Requirements":
            active = True
        if active and node.tag == "p" and not node.text().startswith("Bolded terms"):
            governing = node.text()
        if active and node.tag == "ol":
            number = int(node.attrs.get("start") or next_number)
            for item in node.children:
                if not isinstance(item, Node) or item.tag != "li":
                    continue
                number = int(item.attrs.get("value") or number)
                locator = f"{source_id}:requirements.{number}"
                if locator in requirements:
                    raise ValueError("duplicate requirement numbering")
                # Nested clauses remain inside the parent; never flattened into new IDs.
                requirements[locator] = governing + " " + item.text()
                context.append(locator + "\n" + requirements[locator])
                number += 1
            next_number = number
        else:
            context.append(node.text())
    expected = {f"{source_id}:requirements.{n}" for n in range(1, EXPECTED_COUNTS[source_id] + 1)}
    if set(requirements) != expected:
        raise ValueError("requirement numbering/count differs from reviewed structure")
    return {
        "requirements": requirements,
        "context": "\n".join(context),
        "defined_terms": sorted({n.text() for n in article.descendants("strong")}),
        "linked_dependencies": sorted(
            {n.attrs["href"] for n in article.descendants("a") if n.attrs.get("href")}
        ),
    }


def load_pack(subject_path: Path, artifact_root: Path) -> dict[str, Any]:
    subject = json.loads(subject_path.read_text())
    manifest = json.loads((subject_path.parent / subject["source_pack"]).read_text())
    rubric = json.loads((subject_path.parent / subject["rubric"]).read_text())
    ids = [s["id"] for s in manifest["sources"]]
    if len(ids) != len(set(ids)) or set(ids) != {*EXPECTED_COUNTS, "cmto_effective_date"}:
        raise ValueError("unexpected source set")
    articles = {}
    for source in manifest["sources"]:
        content = {}
        for kind in ("raw", "normalized"):
            path = (artifact_root / source[f"{kind}_path"]).resolve()
            if not path.is_relative_to(artifact_root.resolve()):
                raise ValueError("artifact path escapes root")
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != source[f"{kind}_sha256"]:
                raise ValueError(f"source hash mismatch: {source['id']} ({kind})")
            content[kind] = data
        if len(content["raw"]) != source["byte_length"]:
            raise ValueError("source byte length mismatch")
        if source["id"] in EXPECTED_COUNTS:
            articles[source["id"]] = extract(content["raw"], source["id"])
    check_ids = [c["id"] for c in rubric["checks"]]
    if not check_ids or len(check_ids) != len(set(check_ids)):
        raise ValueError("empty or duplicate rubric checks")
    pack = {
        "subject": subject,
        "rubric": rubric,
        "capture": manifest,
        "extraction_version": EXTRACTION_VERSION,
        "articles": articles,
        "allowed_locators": [
            f"{source}:requirements.{number}"
            for source, numbers in ALLOWED.items()
            for number in numbers
        ],
        "review_status": "structure_checked_not_independent_domain_approval",
    }
    return {**pack, "pack_hash": digest(pack)}
