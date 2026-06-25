#!/usr/bin/env python3
"""vivarium-report — publication-grade comparative-genomics figures (Python backend).

Subcommands:
  heatmap   square/rect matrix TSV/CSV (e.g. ANI/AAI)     -> annotated heatmap
  bars      category-count TSV/CSV (cat col + sample cols) -> grouped or stacked bars

Styling follows Nature-style publication conventions: Arial, small fonts, editable text
in SVG/PDF, spines off. Exports SVG (editable) + PDF + TIFF (600 dpi, LZW-compressed).
Never auto-installs anything; if a package is missing it stops and says which.
"""
import argparse
import shlex
import sys

try:
    import numpy as np
    import pandas as pd
    import matplotlib as mpl
    mpl.use("Agg")
    import matplotlib.pyplot as plt
except ImportError as e:
    sys.stderr.write(f"ERROR: missing Python package: {e.name}. Install it (do NOT auto-install) "
                     f"or use the R backend (plot.R).\n")
    sys.exit(1)

mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"],
    "svg.fonttype": "none",   # editable text in SVG
    "pdf.fonttype": 42,       # editable TrueType text in PDF
    "font.size": 7,
    "axes.spines.right": False,
    "axes.spines.top": False,
    "axes.linewidth": 0.8,
    "legend.frameon": False,
})


def die(msg):
    sys.stderr.write(f"ERROR: {msg}\n")
    sys.exit(1)


def read_table(path, **kw):
    try:
        return pd.read_csv(path, sep=None, engine="python", **kw)  # sniffs tab/comma
    except FileNotFoundError:
        die(f"input not found: {path}")
    except Exception as e:
        die(f"could not read {path}: {e}")


def save_pub(fig, out, action, dpi=600):
    fig.savefig(f"{out}.svg", bbox_inches="tight")
    fig.savefig(f"{out}.pdf", bbox_inches="tight")
    fig.savefig(f"{out}.tiff", dpi=dpi, bbox_inches="tight",
                pil_kwargs={"compression": "tiff_lzw"})
    # Provenance footer (same shape the vivarium shell runners print): a figure with no
    # version stamp is unreproducible three months later when you write the methods.
    pyver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    cmd = "plot.py " + " ".join(shlex.quote(x) for x in sys.argv[1:])
    print(f"=== vivarium-report {action} done ===")
    print(f"tool:    matplotlib {mpl.__version__} (pandas {pd.__version__}, numpy {np.__version__}, Python {pyver})")
    print(f"command: {cmd}")
    print(f"out:     {out}.svg / {out}.pdf / {out}.tiff  ({dpi} dpi, LZW)")


def cmd_heatmap(a):
    df = read_table(a.input, index_col=0)
    try:
        data = df.to_numpy(dtype=float)
    except (ValueError, TypeError):
        die("heatmap input must be a numeric matrix with row labels in column 1.")
    nr, nc = data.shape
    fig, ax = plt.subplots(figsize=(max(3.0, 0.5 * nc + 1.6), max(2.6, 0.5 * nr + 1.0)))
    im = ax.imshow(data, cmap=a.cmap, vmin=a.vmin, vmax=a.vmax, aspect="auto")
    ax.set_xticks(range(nc)); ax.set_xticklabels(df.columns, rotation=45, ha="right")
    ax.set_yticks(range(nr)); ax.set_yticklabels(df.index)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    if a.annot:
        if nr * nc > 225:
            print(f"NOTE: {nr}x{nc} matrix is large; skipping cell annotations for legibility.")
        else:
            for i in range(nr):
                for j in range(nc):
                    v = data[i, j]
                    if v == v:  # not NaN
                        r, g, b, _ = im.cmap(im.norm(v))  # actual background colour at this cell
                        lum = 0.299 * r + 0.587 * g + 0.114 * b
                        ax.text(j, i, f"{v:.{a.dec}f}", ha="center", va="center",
                                fontsize=5.5, color="black" if lum > 0.55 else "white")
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cb.ax.tick_params(labelsize=6, length=2)
    cb.set_label(a.cbar_label or "value", fontsize=6.5)
    if a.title:
        ax.set_title(a.title, fontsize=7.5, fontweight="bold")
    save_pub(fig, a.out, "heatmap", a.dpi)


def cmd_bars(a):
    df = read_table(a.input)
    cat = df.columns[0]
    series = list(df.columns[1:])
    if not series:
        die("bars needs a category column plus >=1 numeric value column.")
    try:
        for s in series:
            df[s] = df[s].astype(float)
    except (ValueError, TypeError):
        die("bars value columns must all be numeric.")
    x = np.arange(len(df))
    fig, ax = plt.subplots(figsize=(max(3.5, 0.5 * len(df) + 1.5), 3.0))
    cmap = plt.get_cmap("tab10")
    if len(series) > 10:
        print(f"NOTE: {len(series)} series exceeds the 10-colour palette; colours will repeat.")
    if a.stacked:
        bottom = np.zeros(len(df))
        for k, s in enumerate(series):
            vals = df[s].to_numpy(dtype=float)
            ax.bar(x, vals, bottom=bottom, width=0.7, label=s, color=cmap(k % 10), edgecolor="none")
            bottom += vals
    else:
        w = 0.8 / len(series)
        for k, s in enumerate(series):
            ax.bar(x + (k - (len(series) - 1) / 2.0) * w, df[s].to_numpy(dtype=float),
                   width=w, label=s, color=cmap(k % 10), edgecolor="none")
    ax.set_xticks(x); ax.set_xticklabels(df[cat], rotation=45, ha="right")
    ax.set_ylabel(a.ylabel or "count")
    ax.tick_params(length=2)
    if len(series) > 1:
        ax.legend(fontsize=6, ncol=1, loc="best")
    if a.title:
        ax.set_title(a.title, fontsize=7.5, fontweight="bold")
    save_pub(fig, a.out, "bars", a.dpi)


def main():
    p = argparse.ArgumentParser(description="vivarium-report Python plotter (publication-grade figures).")
    sub = p.add_subparsers(dest="cmd", required=True)

    h = sub.add_parser("heatmap", help="matrix TSV/CSV -> annotated heatmap")
    h.add_argument("--input", required=True)
    h.add_argument("--out", required=True)
    h.add_argument("--cmap", default="viridis")
    h.add_argument("--vmin", type=float, default=None)
    h.add_argument("--vmax", type=float, default=None)
    h.add_argument("--annot", action="store_true")
    h.add_argument("--dec", type=int, default=2)
    h.add_argument("--cbar-label", dest="cbar_label", default=None)
    h.add_argument("--title", default=None)
    h.add_argument("--dpi", type=int, default=600)
    h.set_defaults(func=cmd_heatmap)

    b = sub.add_parser("bars", help="category-count TSV/CSV -> bar chart")
    b.add_argument("--input", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--stacked", action="store_true")
    b.add_argument("--ylabel", default=None)
    b.add_argument("--title", default=None)
    b.add_argument("--dpi", type=int, default=600)
    b.set_defaults(func=cmd_bars)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
