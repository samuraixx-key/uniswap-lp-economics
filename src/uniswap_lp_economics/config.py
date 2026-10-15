"""Project-wide constants and settings loaded from .env."""

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Uniswap V3 USDC/WETH 0.05% on Ethereum mainnet.
POOL_ADDRESS = "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640"
FEE_PIPS = 500  # 0.05%
TICK_SPACING = 10
DECIMALS0 = 6  # USDC
DECIMALS1 = 18  # WETH
USDC_ADDRESS = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
WETH_ADDRESS = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
NPM_ADDRESS = "0xc36442b4a4522e871399cd717abdd847ab11fe88"  # NonfungiblePositionManager
POOL_CREATED = date(2021, 5, 4)
BLOCK_TIME_S = 12

# Time units: timestamps are integer microseconds since the epoch.
US = 1_000_000  # microseconds per second
HOUR_US = 3600 * US
DAY_S = 86_400

GCP_PROJECT = os.getenv("GCP_PROJECT", "uniswap-lp-economics")
ETH_RPC_URL = os.getenv("ETH_RPC_URL")

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))

WINDOW_START = date(2026, 7, 1)
WINDOW_END = date(2026, 10, 1)  # exclusive
HORIZONS_S = (0, 12, 60, 300, 3600)  # markout horizons after the block timestamp

# On-chain validation samples (fetch-samples) and the coverage C3 demands of them.
N_SAMPLES = 500
N_FULL_BOOK = 5  # of the N_SAMPLES blocks, how many read the full tick book

RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
PROCESSED_DIR = DATA_DIR / "processed"
RESULTS_DIR = ROOT / "results"
VALIDATION_DIR = ROOT / "data_validation"
LABELS_CSV = ROOT / "labels" / "addresses.csv"
LP_LABELS_CSV = ROOT / "labels" / "lp_addresses.csv"

# MEV-Boost relays with a public data API (spec D6).
RELAYS = (
    "https://boost-relay.flashbots.net",
    "https://relay.ultrasound.money",
    "https://bloxroute.max-profit.blxrbdn.com",
    "https://agnostic-relay.net",
    "https://aestus.live",
    "https://titanrelay.xyz",
)
N_RELAY_SAMPLES = 1000
