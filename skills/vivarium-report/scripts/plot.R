#!/usr/bin/env Rscript
# vivarium-report — publication-grade comparative-genomics figures (R backend).
#
# Usage:
#   Rscript plot.R heatmap --input M.tsv --out fig [--annot] [--vmin 95] [--vmax 100] [--cbar-label "ANI (%)"] [--title T]
#   Rscript plot.R bars    --input C.tsv --out fig [--stacked] [--ylabel count] [--title T]
#
# Styling: Nature-style (Helvetica, small fonts, editable text, no panel grid).
# Exports SVG (editable) + PDF + TIFF (600 dpi, LZW). Never auto-installs; names missing packages.

if (!requireNamespace("ggplot2", quietly = TRUE)) {
  cat("ERROR: R package 'ggplot2' not installed. Install it (do NOT auto-install) or use the Python backend (plot.py).\n",
      file = stderr()); quit(status = 1)
}
suppressMessages(library(ggplot2))

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) { cat("ERROR: need a subcommand: heatmap | bars\n", file = stderr()); quit(status = 1) }
cmd  <- args[1]; rest <- args[-1]
flag_present <- function(f) any(rest == f)
getopt <- function(f, default = NA) { i <- which(rest == f); if (length(i) == 0) return(default); rest[i + 1] }
die <- function(msg) { cat(sprintf("ERROR: %s\n", msg), file = stderr()); quit(status = 1) }

input <- getopt("--input"); out <- getopt("--out"); title <- getopt("--title", "")
# Helvetica is a base-14 PostScript font every R device resolves; "Arial" breaks cairo_pdf
# ("invalid font type") on many systems. Helvetica is the Arial-equivalent.
font <- getopt("--font", "Helvetica")
if (is.na(input) || is.na(out)) die("--input and --out are required")
if (!file.exists(input)) die(sprintf("input not found: %s", input))

# delimiter sniff so a .csv works too (parity with the Python backend)
read_auto <- function(path, row_names = FALSE) {
  first <- readLines(path, n = 1, warn = FALSE)
  sep <- if (grepl("\t", first)) "\t" else if (grepl(",", first)) "," else "\t"
  rn <- if (row_names) 1 else NULL
  read.table(path, sep = sep, header = TRUE, row.names = rn, check.names = FALSE,
             quote = "\"", comment.char = "", stringsAsFactors = FALSE)
}

base_theme <- theme_classic(base_size = 7, base_family = font) +
  theme(axis.line   = element_line(linewidth = 0.35, colour = "black"),
        axis.ticks  = element_line(linewidth = 0.35, colour = "black"),
        legend.title = element_text(size = 6.2),
        legend.text  = element_text(size = 5.8),
        plot.title   = element_text(size = 7.5, face = "bold"),
        panel.grid   = element_blank())

write_pdf <- function(plot, file, w, h) {
  ok <- FALSE
  if (capabilities("cairo")) {
    ok <- tryCatch({
      grDevices::cairo_pdf(file, width = w, height = h); print(plot); grDevices::dev.off()
      file.exists(file) && file.info(file)$size > 1000
    }, error = function(e) { try(grDevices::dev.off(), silent = TRUE); FALSE },
       warning = function(w) { try(grDevices::dev.off(), silent = TRUE); FALSE })
  }
  if (!ok) {
    ggsave(file, plot, width = w, height = h, device = "pdf")
    cat("NOTE: PDF uses non-embedded base-14 Helvetica (cairo unavailable). It renders identically in\n",
        "      standard viewers; for strict font embedding install cairo support or run grDevices::embedFonts().\n",
        file = stderr())
  }
}

save_pub_r <- function(plot, filename, width_mm = 120, height_mm = 90, dpi = 600) {
  w <- width_mm / 25.4; h <- height_mm / 25.4
  if (requireNamespace("svglite", quietly = TRUE)) {
    svglite::svglite(paste0(filename, ".svg"), width = w, height = h); print(plot); dev.off()
  } else ggsave(paste0(filename, ".svg"), plot, width = w, height = h)
  write_pdf(plot, paste0(filename, ".pdf"), w, h)
  if (requireNamespace("ragg", quietly = TRUE)) {
    ragg::agg_tiff(paste0(filename, ".tiff"), width = w, height = h, units = "in", res = dpi, compression = "lzw")
    print(plot); dev.off()
  } else ggsave(paste0(filename, ".tiff"), plot, width = w, height = h, dpi = dpi)
  # Provenance footer (same shape the vivarium shell runners print): a figure with no
  # version stamp is unreproducible later when you write the methods. cmd/args are globals.
  svg_v  <- if (requireNamespace("svglite", quietly = TRUE)) as.character(packageVersion("svglite")) else "absent"
  ragg_v <- if (requireNamespace("ragg",    quietly = TRUE)) as.character(packageVersion("ragg"))    else "absent"
  cat(sprintf("=== vivarium-report %s done ===\n", cmd))
  cat(sprintf("tool:    ggplot2 %s (svglite %s, ragg %s, %s)\n",
              as.character(packageVersion("ggplot2")), svg_v, ragg_v, R.version.string))
  cat(sprintf("command: plot.R %s\n", paste(args, collapse = " ")))
  cat(sprintf("out:     %s.svg / %s.pdf / %s.tiff (%d dpi, LZW)\n", filename, filename, filename, dpi))
}

if (cmd == "heatmap") {
  m <- as.matrix(read_auto(input, row_names = TRUE))
  if (!is.numeric(m)) die("heatmap input must be a numeric matrix with row labels in column 1.")
  vmin <- getopt("--vmin"); vmax <- getopt("--vmax")
  rng <- if (!is.na(vmin) && !is.na(vmax)) c(as.numeric(vmin), as.numeric(vmax)) else range(m, na.rm = TRUE)
  df <- expand.grid(row = rownames(m), col = colnames(m), stringsAsFactors = FALSE)
  df$value <- as.vector(m)
  df$row <- factor(df$row, levels = rev(rownames(m)))
  df$col <- factor(df$col, levels = colnames(m))
  # contrast-aware label colour: viridis is dark at low values (white text) and light at high (black text)
  norm <- (df$value - rng[1]) / (rng[2] - rng[1])
  df$txtcol <- ifelse(is.na(norm), "black", ifelse(norm > 0.6, "black", "white"))
  cbl <- getopt("--cbar-label", "value")
  p <- ggplot(df, aes(col, row, fill = value)) +
    geom_tile(colour = "white", linewidth = 0.15) +
    scale_fill_viridis_c(name = cbl, limits = rng) +
    labs(x = NULL, y = NULL, title = title) +
    base_theme +
    theme(axis.text.x = element_text(angle = 45, hjust = 1))
  if (flag_present("--annot")) {
    p <- p + geom_text(aes(label = ifelse(is.na(value), "", sprintf("%.2f", value)), colour = txtcol), size = 1.9) +
      scale_colour_identity()
  }
  save_pub_r(p, out, width_mm = max(80, 12 * ncol(m) + 40), height_mm = max(70, 12 * nrow(m) + 30))

} else if (cmd == "bars") {
  d <- read_auto(input, row_names = FALSE)
  catcol <- names(d)[1]
  ser <- names(d)[-1]
  if (length(ser) < 1) die("bars needs a category column plus >=1 value column")
  for (s in ser) if (!is.numeric(d[[s]])) die(sprintf("bars value column '%s' is not numeric", s))
  long <- do.call(rbind, lapply(ser, function(s)
    data.frame(category = d[[catcol]], series = s, value = d[[s]], stringsAsFactors = FALSE)))
  long$category <- factor(long$category, levels = d[[catcol]])
  long$series   <- factor(long$series, levels = ser)   # keep input (genome) order, not alphabetical
  pos <- if (flag_present("--stacked")) "stack" else "dodge"
  yl  <- getopt("--ylabel", "count")
  fillscale <- if (length(ser) <= 8) scale_fill_brewer(palette = "Set2") else scale_fill_viridis_d()
  p <- ggplot(long, aes(category, value, fill = series)) +
    geom_col(position = pos, width = 0.7) +
    fillscale +
    labs(x = NULL, y = yl, fill = NULL, title = title) +
    base_theme +
    theme(axis.text.x = element_text(angle = 45, hjust = 1))
  if (length(ser) == 1) p <- p + theme(legend.position = "none")
  save_pub_r(p, out, width_mm = max(90, 10 * nrow(d) + 40))

} else {
  die(sprintf("unknown subcommand '%s' (use heatmap | bars)", cmd))
}
