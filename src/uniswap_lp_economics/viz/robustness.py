"""Chapter 'Is it the reference price?': fees - LVR by reference and t0 offset, with the measured
winning-bid times and the protocol's fee cut (figure 13, sub-project 4 spec section 6)."""

from matplotlib.figure import Figure

from uniswap_lp_economics.lp import robustness as lp_robustness
from uniswap_lp_economics.viz.data import Results
from uniswap_lp_economics.viz.hero import spread
from uniswap_lp_economics.viz.style import USD_FMT, fade_band, frame, new_figure, pal, usd

LOW, HIGH = lp_robustness.OFFSETS_S[0], lp_robustness.OFFSETS_S[-1]
NEUTRAL = "Whether LPs lose depends on when the reference price is read"


def title(
    crossings: dict[str, float | None], p10_s: float | None, curve_after_zero_negative: bool
) -> str:
    """The finding, only where the data supports it: every line below zero from slot start on,
    and the latest crossing earlier than the measured winning bids."""
    if not curve_after_zero_negative:
        return NEUTRAL
    found = [c for c in crossings.values() if c is not None]
    if not found:
        return f"LPs lose at every reference and every offset from −{-LOW:g} s to +{HIGH:g} s"
    latest = max(found)
    if latest >= 0 or (p10_s is not None and latest >= p10_s):
        return NEUTRAL
    return f"LPs lose at every reference unless prices are read {-latest:.1f} s before the slot"


def reference_and_timing(r: Results) -> Figure:
    p = pal()
    lp = r.summary["lp"]
    rob = lp["robustness"]
    timing = rob["timing"]
    fig, ax = new_figure(right=0.78)
    lines = {
        name: r.robustness.filter(r.robustness["reference"] == name).sort("offset_s")
        for name in lp_robustness.REFERENCES
    }
    primary = lines[lp_robustness.REFERENCES[0]]
    x = primary["offset_s"].to_list()

    has_timing = timing["p10_ms"] is not None
    if has_timing:
        lo_s, hi_s = timing["p10_ms"] / 1000, timing["p90_ms"] / 1000
        ax.axvspan(lo_s, hi_s, color=p.faint, alpha=0.16, lw=0)
        ax.annotate(
            "winning bids",
            ((lo_s + hi_s) / 2, 1),
            xycoords=("data", "axes fraction"),
            xytext=(0, -4),
            textcoords="offset points",
            ha="center",
            va="top",
            fontsize=8.5,
            color=p.muted,
        )
    ax.axhline(0, color=p.ink, lw=0.9)
    cut = -float(lp["protocol_fees_usd"])
    ax.axhline(cut, color=p.protocol, lw=1.1, ls=(0, (4, 3)))
    ax.annotate(
        f"protocol fee cut  {usd(cut)}",
        (LOW, cut),
        xytext=(4, 4),
        textcoords="offset points",
        fontsize=8.5,
        color=p.protocol,
    )
    fade_band(ax, x, primary["ci_lo_usd"].to_list(), primary["ci_hi_usd"].to_list(), p.lvr)
    for name, rows in reversed(lines.items()):  # the primary on top
        is_primary = name == lp_robustness.REFERENCES[0]
        ax.plot(
            rows["offset_s"].to_list(),
            rows["fees_minus_lvr_usd"].to_list(),
            color=p.lvr if is_primary else p.muted,
            lw=2.4 if is_primary else 1.3,
            alpha=1.0 if is_primary else 0.9,
            zorder=3 if is_primary else 2,
        )
    zero = primary.filter(primary["offset_s"] == 0)["fees_minus_lvr_usd"][0]
    ax.scatter([0], [zero], s=36, color=p.lvr, zorder=4)
    ax.annotate(
        f"headline {usd(zero)}",
        (0, zero),
        xytext=(-8, -12),
        textcoords="offset points",
        ha="right",
        fontsize=9,
        color=p.lvr,
    )
    ax.set_xlim(LOW, HIGH)
    ax.yaxis.set_major_formatter(USD_FMT)
    ax.set_xlabel("Seconds from slot start at which the reference price is read")
    ax.set_ylabel("LP fees − LVR")

    # Right-end labels, top to bottom, kept apart.
    ends = sorted(
        ((float(rows["fees_minus_lvr_usd"][-1]), name) for name, rows in lines.items()),
        reverse=True,
    )
    y0, y1 = ax.get_ylim()
    placed = spread([y for y, _ in ends], 0.05 * (y1 - y0), y0)
    for (y, name), at in zip(ends, placed, strict=True):
        ax.annotate(
            lp_robustness.REFERENCE_LABELS[name],
            (HIGH, y),
            xytext=(HIGH + 0.12, at),
            textcoords="data",
            va="center",
            fontsize=9.5,
            fontweight="bold" if name == lp_robustness.REFERENCES[0] else "normal",
            color=p.lvr if name == lp_robustness.REFERENCES[0] else p.muted,
            annotation_clip=False,
        )

    after_zero = r.robustness.filter(r.robustness["offset_s"] >= 0)
    p50 = timing["p50_ms"]
    median = rob["fees_minus_lvr_at_median_timing_usd"]
    frame(
        fig,
        title(
            rob["crossing_offset_s"],
            lo_s if has_timing else None,
            bool((after_zero["fees_minus_lvr_usd"] < 0).all()),
        ),
        "LP fees − LVR with the reference read at slot start + offset. "
        f"At 0 s (the headline) {usd(zero)}"
        + (
            f"; at the median winning bid (+{p50 / 1000:.1f} s) {usd(median)}"
            if p50 is not None and median is not None
            else ""
        )
        + f". Dashed: the protocol's fee cut ({usd(-cut)}).",
        (
            f"Winning bids: 10th–90th percentile on {timing['n_timed']:,} blocks delivered "
            "through Titan, Flashbots and Aestus; ultrasound, the largest relay, keeps no bid "
            "history for this window. "
            if has_timing
            else "No winning-bid times were available. "
        )
        + "Band on the primary line: 95% day bootstrap.",
    )
    return fig
