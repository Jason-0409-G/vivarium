#!/usr/bin/env python3
"""Authoritative data figures for the vivarium durable-loop test campaign.

All numbers are real, from this campaign's fresh experiments (see benchmark/*.md):
  - scale-drift crossover: recall of earliest facts when project state FITS vs
    EXCEEDS a carry budget (self-managed handoff vs durable ledger).
  - 2x3 token cost: no-skill vs vivarium output tokens per model tier.
English in-chart labels avoid CJK font issues; captions live in the report.

Run:  /opt/anaconda3/bin/python3 benchmark/make_authoritative_figures.py
"""
from __future__ import annotations

import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = "#94a3b8"       # self-managed handoff / no-skill
ACCENT = "#0d9488"     # durable ledger / vivarium
INK = "#0f172a"
MUTED = "#64748b"
GRID = "#e2e8f0"
RED = "#b91c1c"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 11,
    "axes.edgecolor": "#cbd5e1", "axes.linewidth": 0.9, "svg.fonttype": "none",
})
OUT = pathlib.Path(__file__).resolve().parent.parent / "docs" / "figures"
OUT.mkdir(parents=True, exist_ok=True)


def _style(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(length=0)
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color=GRID, linewidth=0.9)


def _lab(ax, bars, fmt, dy=0):
    for b in bars:
        h = b.get_height()
        ax.text(b.get_x() + b.get_width() / 2, h + dy, fmt(h), ha="center",
                va="bottom", fontsize=10, color=INK, fontweight="bold")


def save(fig, stem):
    for ext in ("svg", "png"):
        fig.savefig(OUT / f"{stem}.{ext}", dpi=192, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---- Headline: the scale crossover -----------------------------------------
def figure_crossover():
    fig, ax = plt.subplots(figsize=(9.6, 5.0))
    groups = ["State FITS context\n(72 facts, unbounded handoff)",
              "State EXCEEDS carry budget\n(180 facts, 500-char handoff)"]
    self_managed = [100.0, 8.3]   # exceeds: strongest model (Opus) recalling its own bounded handoff
    ledger = [100.0, 100.0]       # exceeds: weakest model (Haiku) reading the durable ledger
    x = range(len(groups)); w = 0.36
    b1 = ax.bar([i - w / 2 for i in x], self_managed, w,
                label="self-managed handoff (model's own state)", color=BASE)
    b2 = ax.bar([i + w / 2 for i in x], ledger, w,
                label="durable ledger (vivarium)", color=ACCENT)
    _lab(ax, b1, lambda h: f"{h:.0f}%")
    _lab(ax, b2, lambda h: f"{h:.0f}%")
    ax.set_xticks(list(x)); ax.set_xticklabels(groups)
    ax.set_ylim(0, 116)
    ax.set_ylabel("recall of earliest facts (%)")
    ax.set_title("Memory integrity vs. project scale — the crossover",
                 fontsize=13.5, color=INK, fontweight="bold", loc="left")
    ax.legend(frameon=False, fontsize=10, loc="upper center", ncol=2, bbox_to_anchor=(0.5, -0.13))
    # call-outs
    ax.annotate("strongest model (Opus)\nstill only 8%", xy=(1 - w / 2, 8.3), xytext=(0.55, 42),
                fontsize=9.5, color=RED, fontweight="bold", ha="center",
                arrowprops=dict(arrowstyle="->", color=RED, lw=1.2))
    ax.annotate("weakest model (Haiku)\nexact via ledger", xy=(1 + w / 2, 100), xytext=(0.74, 82),
                fontsize=9.5, color=ACCENT, fontweight="bold", ha="center",
                arrowprops=dict(arrowstyle="->", color=ACCENT, lw=1.2))
    _style(ax)
    fig.subplots_adjust(bottom=0.18, top=0.90)
    save(fig, "benchmark_scale_crossover")


# ---- 2x3 token cost (small-scale: durable loop is a NET COST) ---------------
def figure_tokens():
    fig, ax = plt.subplots(figsize=(8.8, 4.6))
    tiers = ["Opus 4.8", "Sonnet 5", "Haiku 4.5"]
    noskill = [39849, 46036, 40168]
    vivarium = [68728, 90028, 50203]
    x = range(len(tiers)); w = 0.36
    b1 = ax.bar([i - w / 2 for i in x], noskill, w, label="no-skill", color=BASE)
    b2 = ax.bar([i + w / 2 for i in x], vivarium, w, label="vivarium (durable loop)", color=ACCENT)
    _lab(ax, b1, lambda h: f"{int(h/1000)}k")
    _lab(ax, b2, lambda h: f"{int(h/1000)}k")
    ax.set_xticks(list(x)); ax.set_xticklabels(tiers)
    ax.set_ylim(0, 108000)
    ax.set_ylabel("output tokens (single run)")
    ax.set_title("Small-scale task: the durable loop is a net token cost",
                 fontsize=12.5, color=INK, fontweight="bold", loc="left")
    ax.legend(frameon=False, fontsize=10, loc="upper right")
    for i, (n, v) in enumerate(zip(noskill, vivarium)):
        ax.text(i + w / 2, v + 6200, f"+{round(100*(v-n)/n)}%", ha="center", fontsize=9.5,
                color=RED, fontweight="bold")
    _style(ax)
    fig.subplots_adjust(bottom=0.10, top=0.89)
    save(fig, "benchmark_2x3_tokens")


if __name__ == "__main__":
    figure_crossover()
    figure_tokens()
    print("wrote:", *(p.name for p in sorted(OUT.glob("benchmark_scale_crossover.*")) +
                       sorted(OUT.glob("benchmark_2x3_tokens.*"))))
