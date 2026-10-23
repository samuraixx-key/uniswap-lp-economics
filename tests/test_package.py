"""Package-level settings that every pipeline step relies on."""

import os
import subprocess
import sys


def test_importing_the_package_pins_polars_to_16_threads() -> None:
    # parallel steps split frames into one chunk per thread, and the chunks set the parquet row
    # groups the strategy freeze hashes: the pool must not depend on the machine's core count
    env = {k: v for k, v in os.environ.items() if k != "POLARS_MAX_THREADS"}
    code = (
        "import os, uniswap_lp_economics, polars; "
        "print(os.environ['POLARS_MAX_THREADS'], polars.thread_pool_size())"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
    )
    assert out.stdout.split() == ["16", "16"]


def test_an_explicit_thread_count_is_respected() -> None:
    env = {**os.environ, "POLARS_MAX_THREADS": "2"}
    code = "import uniswap_lp_economics, polars; print(polars.thread_pool_size())"
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "2"
