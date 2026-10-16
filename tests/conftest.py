from collections.abc import Iterator

import matplotlib.pyplot as plt
import pytest


@pytest.fixture(autouse=True)
def _close_figures() -> Iterator[None]:
    """Figures drawn by a test are closed after it, so the suite never piles them up."""
    yield
    plt.close("all")
