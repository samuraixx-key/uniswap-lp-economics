"""Uniswap V3 LP economics: fees, LVR and flow markouts on USDC/WETH 0.05%."""

import os

# Before anything imports polars: its parallel steps split frames into one chunk per thread, and
# the chunks set the parquet row groups whose bytes the strategy freeze hashes. 16 is the pool the
# committed results were written with; fixing it keeps re-runs byte-identical on any machine.
os.environ.setdefault("POLARS_MAX_THREADS", "16")
