"""MkDocs hooks: serve the committed figures and fonts from their repo paths.

Site pages write figure paths that are correct on GitHub (docs/ is one level below the repo
root). On the site the same files sit at the site root, so one leading ../ is dropped.
"""

import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SERVED = (
    "results/figures/*.svg",
    "results/figures/*.gif",
    "assets/fonts/*.ttf",
    "assets/fonts/LICENSE.txt",
)
_FIGURE_LINK = re.compile(r'(\]\(|src=")\.\./((?:\.\./)*results/figures/)')


def site_figure_paths(markdown: str) -> str:
    return _FIGURE_LINK.sub(r"\1\2", markdown)


def on_page_markdown(markdown: str, page: Any, config: Any, files: Any) -> str:
    return site_figure_paths(markdown)


def on_files(files: Any, config: Any) -> Any:
    from mkdocs.structure.files import File

    for pattern in SERVED:
        for path in sorted(ROOT.glob(pattern)):
            files.append(
                File(
                    path.relative_to(ROOT).as_posix(),
                    str(ROOT),
                    config["site_dir"],
                    config["use_directory_urls"],
                )
            )
    return files
