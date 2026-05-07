from dataclasses import dataclass


def _pass_region(op, threshold, nominal):
    """Return ``(pass_lo, pass_hi)`` for a spec operator — the
    inclusive bounds of the passing range on the metric axis. ``None``
    on either side means unbounded. Used by ``YieldReport.plot`` to
    shade everything *outside* this region as the fail zone."""
    if op == "<":  return (None, threshold)
    if op == "<=": return (None, threshold)
    if op == ">":  return (threshold, None)
    if op == ">=": return (threshold, None)
    if op == "within":
        if nominal is None:
            return (None, None)
        margin = abs(nominal) * threshold
        return (nominal - margin, nominal + margin)
    if op == "within_db":
        if nominal is None or nominal <= 0:
            return (None, None)
        ratio = 10.0 ** (threshold / 20.0)
        return (nominal / ratio, nominal * ratio)
    return (None, None)


@dataclass
class MetricStats:
    """Distribution of a single metric across all MC samples. Percentiles
    are the conventional summary points: p1/p99 are the long-tail edges
    (1-in-100 events), p5/p95 are the headline-yield edges (commonly
    quoted as the "95% interval"), p50 is the median.

    ``skew`` is the Fisher-Pearson sample skewness — zero for symmetric
    distributions, positive when the right tail is heavier (e.g. amplitude
    metrics that can run away but not below zero), negative for the
    mirror case. ``excess_kurtosis`` is kurtosis minus 3 — zero for a
    Gaussian, positive when the distribution has heavier tails or a
    sharper peak than a Gaussian, negative for flatter / lighter-tailed
    distributions. Bimodal distributions (e.g. an oscillator with a
    'didn't start' spike alongside the main lobe) typically show large
    positive excess kurtosis from the spike concentrating mass in one
    bin, and skew whose sign depends on which lobe is larger and where
    the spike sits relative to the mean."""
    min: float
    max: float
    mean: float
    std: float
    p1: float
    p5: float
    p50: float
    p95: float
    p99: float
    skew: float
    excess_kurtosis: float


@dataclass
class YieldReport:
    samples_total: int
    samples_pass: int
    per_spec_pass: dict
    """``{spec_name: pass_count}``. Marginal pass rate per spec — a low
    overall yield with one spec at near-100% and another at 60% tells
    you which margin to widen."""
    nominal_metrics: dict
    """Metric values evaluated at the un-perturbed nominal — both for
    context and as the reference point used by the ``"within"`` and
    ``"within_db"`` spec operators."""
    metric_stats: dict
    """``{metric_name: MetricStats}`` for every metric returned by the
    ``metrics`` callable (not just those with a spec). Lets you see the
    distribution shape and tails, e.g. how close p95 sits to a spec
    threshold or whether the median has drifted off nominal."""
    failure_modes: dict
    """``{frozenset(failing_specs): count}`` for failing samples only.
    Reveals joint structure that ``per_spec_pass`` marginals hide:
    ``{frozenset({'fc'}): 50, frozenset({'Q'}): 50}`` is two
    independent ~50-sample failures (two binding margins);
    ``{frozenset({'fc', 'Q'}): 50}`` is one joint failure (one binding
    margin, one merely correlated). Empty when yield is 100%."""
    metric_samples: dict
    """``{metric_name: np.ndarray of shape (n_mc,)}`` — the raw per-sample
    metric values. Kept so plots can show the actual histogram (which
    percentiles can't reconstruct). Memory cost: ``n_mc × n_metrics × 8``
    bytes — trivial at MC scales."""
    spec: dict
    """The spec dict the report was computed against
    (``{name: (op, threshold)}``). Stored so plotting can overlay the
    fail region without the caller passing it again."""

    @property
    def yield_pct(self):
        return 100.0 * self.samples_pass / self.samples_total

    def plot(self, metrics=None, bins=50, fail_color="#d62728",
             fail_alpha=0.15):
        """Histogram of each metric with nominal/p5/p50/p95 markers and
        the spec fail region shaded.

        Args:
            metrics: Subset of metric names to plot; default all.
            bins: Histogram bin count (passed to matplotlib).
            fail_color, fail_alpha: Styling for the shaded fail region.

        Returns:
            ``matplotlib.figure.Figure``. Caller decides whether to
            ``show()`` or ``savefig()``.
        """
        import math as _math

        import matplotlib.pyplot as plt

        keys = list(self.metric_samples) if metrics is None else list(metrics)
        n = len(keys)
        ncols = min(3, max(1, n))
        nrows = _math.ceil(n / ncols)
        fig, axes = plt.subplots(
            nrows, ncols, figsize=(5 * ncols, 3.6 * nrows), squeeze=False
        )

        import numpy as np

        for i, name in enumerate(keys):
            ax = axes[i // ncols][i % ncols]
            arr = self.metric_samples[name]
            stats = self.metric_stats.get(name)
            nom = self.nominal_metrics.get(name)

            # Strip NaNs for axis-limit and histogram computation.
            # NaN samples are real (failed simulations, undefined
            # measurements) but matplotlib's hist + set_xlim both
            # break on them. Annotate the count if any are present.
            finite = arr[np.isfinite(arr)]
            n_nan = arr.size - finite.size

            if finite.size == 0:
                ax.text(0.5, 0.5, "all samples NaN",
                        ha="center", va="center", transform=ax.transAxes,
                        fontsize=10, color="#888")
                ax.set_title(f"{name} (no finite samples)")
                ax.set_xticks([]); ax.set_yticks([])
                continue

            data_lo, data_hi = float(finite.min()), float(finite.max())
            data_range = data_hi - data_lo
            pad = data_range * 0.05 if data_range > 0 else \
                  (abs(data_lo) * 0.01 + 1e-12)
            xlim_lo, xlim_hi = data_lo - pad, data_hi + pad

            ax.hist(finite, bins=bins, color="#4c72b0",
                    edgecolor="white", linewidth=0.3)

            if name in self.spec:
                op, thr = self.spec[name]
                pass_lo, pass_hi = _pass_region(op, thr, nom)
                # Shade fail regions clipped to the data-driven xlim.
                # If the threshold sits well outside the data range it
                # just falls off the visible axis — the title still
                # records the spec, and the high yield speaks for itself.
                if pass_lo is not None and pass_lo > xlim_lo:
                    ax.axvspan(xlim_lo, min(pass_lo, xlim_hi),
                               color=fail_color, alpha=fail_alpha)
                if pass_hi is not None and pass_hi < xlim_hi:
                    ax.axvspan(max(pass_hi, xlim_lo), xlim_hi,
                               color=fail_color, alpha=fail_alpha)
                pass_count = self.per_spec_pass.get(name, 0)
                pct = 100.0 * pass_count / self.samples_total
                title = (f"{name}: {op} {thr}  →  "
                         f"{pass_count}/{self.samples_total} ({pct:.1f}%)")
                if n_nan > 0:
                    title += f"  [NaN: {n_nan}]"
                ax.set_title(title)
            else:
                title = f"{name} (no spec)"
                if n_nan > 0:
                    title += f"  [NaN: {n_nan}]"
                ax.set_title(title)

            if nom is not None:
                ax.axvline(nom, color="black", linestyle="--",
                           linewidth=1.2, label=f"nominal={nom:.4g}")
            if stats is not None:
                for pct_label, val in [("p5", stats.p5),
                                       ("p50", stats.p50),
                                       ("p95", stats.p95)]:
                    ax.axvline(val, color="#888", linestyle=":",
                               linewidth=0.9)
                    ax.text(val, ax.get_ylim()[1] * 0.97, pct_label,
                            rotation=90, va="top", ha="right",
                            fontsize=8, color="#555")

            ax.set_xlim(xlim_lo, xlim_hi)
            ax.set_xlabel(name)
            ax.set_ylabel("count")
            ax.legend(loc="upper right", fontsize=8)

        for j in range(n, nrows * ncols):
            axes[j // ncols][j % ncols].axis("off")

        fig.suptitle(
            f"yield: {self.samples_pass}/{self.samples_total} = "
            f"{self.yield_pct:.2f}%",
            fontsize=11,
        )
        fig.tight_layout()
        return fig

    def __str__(self):
        lines = [
            f"yield: {self.samples_pass}/{self.samples_total} = "
            f"{self.yield_pct:.2f}%"
        ]
        for name, count in self.per_spec_pass.items():
            pct = 100.0 * count / self.samples_total
            nom = self.nominal_metrics.get(name)
            stats = self.metric_stats.get(name)
            line = f"  {name}: {count}/{self.samples_total} pass ({pct:.2f}%)"
            if nom is not None:
                line += f"  nominal={nom:.4g}"
            if stats is not None:
                line += (f"  p5={stats.p5:.4g} "
                         f"p50={stats.p50:.4g} "
                         f"p95={stats.p95:.4g}")
            lines.append(line)
        if self.failure_modes:
            lines.append("failure modes:")
            for failing, count in sorted(self.failure_modes.items(),
                                         key=lambda kv: -kv[1]):
                names = ", ".join(sorted(failing))
                pct = 100.0 * count / self.samples_total
                lines.append(f"  {{{names}}}: {count} ({pct:.2f}%)")
        return "\n".join(lines)
