# Cover-art progressive reveal: mathematical model

## Problem

Render an album cover progressively, starting unrecognisable at round
start ($p = 0$) and ending fully clear at round end ($p = 1$). The
reveal must be smooth, monotonic, and tunable.

## Two-stage transform

We compose two independent obscuring transforms whose strengths decay
monotonically with progress.

### Stage 1: Pixelation

Define the pixelation factor

$$f_{\text{pix}}(p) = \mathrm{round}\left( f_{\max} \cdot (1 - p)^{\gamma} + f_{\min} \right), \qquad \gamma = 1.7,$$

with $f_{\max} = 24$ and $f_{\min} = 1$ (no pixelation). The image is
downsampled to $(N / f_{\text{pix}}) \times (N / f_{\text{pix}})$ via
bilinear filtering, then upsampled back to $N \times N$ with
nearest-neighbour interpolation. The nearest-neighbour upsample is what
produces the visible "blocks": each output pixel takes the colour of
the nearest downsampled pixel, so groups of $f_{\text{pix}}^{2}$ pixels
become one large flat patch.

The exponent $\gamma > 1$ concentrates obscuration in the first half of
the round: $f_{\text{pix}}(0.0) = 25$, $f_{\text{pix}}(0.5) \approx 9$,
$f_{\text{pix}}(0.8) \approx 3$, $f_{\text{pix}}(1.0) = 1$. The cover is
essentially solid colour at $p = 0$, recognisable at $p = 0.7$, and
fully resolved by $p = 1$.

### Stage 2: Gaussian blur

After pixelation, we apply a Gaussian blur of standard deviation

$$\sigma(p) = \sigma_{\max} \cdot (1 - p)^{\delta}, \qquad \delta = 1.3,$$

with $\sigma_{\max} = 18$ pixels. The Gaussian kernel softens the hard
edges introduced by nearest-neighbour upsampling and removes the
low-frequency colour cues that would otherwise let a player guess the
cover by overall hue alone (think Pink Floyd's *The Dark Side of the
Moon*: the rainbow prism is identifiable from a single dominant block).

### Composition

The full transform is

$$\mathrm{Reveal}(I, p) = \mathrm{Blur}\!\left( \mathrm{Up}_{\mathrm{NN}}\!\left( \mathrm{Down}_{\mathrm{BL}}\bigl(I,\, f_{\text{pix}}(p)\bigr) \right),\ \sigma(p) \right).$$

The two stages are commutative up to interpolation order; we apply
pixelation first because the blur kernel can be larger than a single
super-pixel late in the round, which is what we want.

## Calibration

Parameters were tuned by hand against a corpus of 50 representative
covers (popular albums spanning 1970–2025) with the goal that:

- At $p = 0.20$ the cover is unguessable for a typical player (a coarse
  colour blob).
- At $p = 0.50$ the silhouette is visible but the title text is not.
- At $p = 0.80$ a familiar cover is recognisable but a less-popular
  cover may still need a few more seconds.

A formal A/B study would be needed to verify these claims; for now the
parameters are exposed as `RevealParams` so they can be tuned per-host
or per-game (see `docs/configuration.md`).

## Why two stages instead of one

Pixelation alone produces blocky silhouettes that experienced players
can decode by colour palette. Blur alone preserves the cover's
silhouette and corner geometry, which is enough to identify many
covers. The combination destroys both cues until both decay to
imperceptible levels near $p = 1$.
