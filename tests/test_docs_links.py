"""Every relative link and #anchor in the tracked Markdown resolves (the report pages go public)."""

import re
import subprocess
from functools import cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FENCE = re.compile(r"^```.*?^```", re.M | re.S)
CODE = re.compile(r"`[^`\n]*`")
LINK = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|\bsrc=\"([^\"]+)\"")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.M)
TAGS = ("holdout-preregistered", "forwarder-preregistered", "strategy-preregistered", "v1.0")


def github_slug(heading: str) -> str:
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def _markdown() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    return [ROOT / f for f in out]


def _text(path: Path) -> str:
    return CODE.sub("", FENCE.sub("", path.read_text(encoding="utf-8")))


@cache
def _anchors(path: Path) -> frozenset[str]:
    seen: dict[str, int] = {}
    out = set()
    for h in HEADING.findall(FENCE.sub("", path.read_text(encoding="utf-8"))):
        s = github_slug(h)
        n = seen.get(s, 0)
        seen[s] = n + 1
        out.add(s if n == 0 else f"{s}-{n}")
    return frozenset(out)


def _links() -> list[tuple[Path, str]]:
    return [(p, a or b) for p in _markdown() for a, b in LINK.findall(_text(p))]


def _local(target: str) -> bool:
    return not re.match(r"[a-z]+:", target)


def test_github_slug() -> None:
    assert github_slug("0. Why these choices") == "0-why-these-choices"
    assert github_slug("Is it the reference price?") == "is-it-the-reference-price"
    assert github_slug("Checks L1–L7 and R1–R6") == "checks-l1l7-and-r1r6"


def test_relative_links_resolve() -> None:
    bad = []
    for src, target in _links():
        path = target.split("#", 1)[0]
        if not _local(target) or not path:
            continue
        dest = ROOT / path.lstrip("/") if path.startswith("/") else src.parent / path
        if not dest.exists():
            bad.append(f"{src.relative_to(ROOT)} -> {target}")
    assert not bad, "\n".join(bad)


def test_anchors_exist() -> None:
    bad = []
    for src, target in _links():
        if not _local(target) or "#" not in target:
            continue
        path, frag = target.split("#", 1)
        dest = (src.parent / path) if path else src
        if dest.suffix == ".md" and dest.exists() and frag not in _anchors(dest.resolve()):
            bad.append(f"{src.relative_to(ROOT)} -> {target}")
    assert not bad, "\n".join(bad)


def test_no_tree_tag_links() -> None:
    bad = [
        f"{p.relative_to(ROOT)}: /tree/{t}"
        for p in _markdown()
        for t in TAGS
        if f"/tree/{t}" in p.read_text(encoding="utf-8")
    ]
    assert not bad, "\n".join(bad)


def _site_pages() -> list[str]:
    pages = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "docs").rglob("*.md"))
    return [p for p in pages if not p.startswith("docs/specs/") and p != "docs/roadmap.md"]


@pytest.mark.parametrize("name", ["README.md", *_site_pages()])
def test_no_validator_wording(name: str) -> None:
    path = ROOT / name
    if path.exists():
        assert "validator" not in path.read_text(encoding="utf-8").lower()


def test_html_blocks_end_before_markdown() -> None:
    # github.com renders Markdown inside an HTML block only after a blank line
    bad = [
        f"{p}: {m.group(0)!r}"
        for p in _site_pages()
        for m in re.finditer(
            r"<(figure|div|details)\b[^>]*\bmarkdown\b[^>]*>\n(?![\n<])[^\n]*",
            (ROOT / p).read_text(encoding="utf-8"),
        )
    ]
    assert not bad, "\n".join(bad)


def test_github_figure_paths() -> None:
    # site pages use repo-relative figure paths so github.com shows them; the hook strips one ../
    bad = [
        f"{s.relative_to(ROOT)} -> {t}"
        for s, t in _links()
        if "results/figures/" in t and _local(t) and not (s.parent / t).resolve().exists()
    ]
    assert not bad, "\n".join(bad)


def test_anchors_keep_inline_code(tmp_path: Path) -> None:
    md = tmp_path / "x.md"
    md.write_text("### 3.2 `notional_usd`\n", encoding="utf-8")
    assert "32-notional_usd" in _anchors(md)


def test_no_directory_links() -> None:
    # GitHub Pages has no directory index: a link to a folder is a 404 on the site
    bad = []
    for src, target in _links():
        path = target.split("#", 1)[0]
        if _local(target) and path and (src.parent / path).is_dir():
            bad.append(f"{src.relative_to(ROOT)} -> {target}")
    assert not bad, "\n".join(bad)
