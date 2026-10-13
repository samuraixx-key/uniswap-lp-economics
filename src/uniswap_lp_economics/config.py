"""Project-wide constants and settings loaded from .env."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Uniswap V3 USDC/WETH 0.05% on Ethereum mainnet.
POOL_ADDRESS = "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640"
FEE_PIPS = 500  # 0.05%
TICK_SPACING = 10
DECIMALS0 = 6  # USDC
DECIMALS1 = 18  # WETH

GCP_PROJECT = os.getenv("GCP_PROJECT", "uniswap-lp-economics")
ETH_RPC_URL = os.getenv("ETH_RPC_URL")

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
