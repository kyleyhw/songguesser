"""Progressive cover-art reveal.

Mathematical model
------------------
Let the round progress be ``p ∈ [0, 1]``, defined as
``p = elapsed / duration``. The cover art is rendered through two parallel
obscuring transforms whose strength decays monotonically with ``p``:

  1. *Pixelation.* The input image is downsampled by an integer factor

         f_pix(p) = round( f_max · (1 - p)^γ + f_min )   (γ = 1.7)

     and then nearest-neighbour upsampled back to the original size.
     ``f_max = 24`` blocks and ``f_min = 1`` (i.e. fully resolved).
     The exponent ``γ > 1`` makes the early game very pixelated and the
     final third nearly clear, which empirically matches the perceptual
     "guessability ramp" expected of a binb-style game.

  2. *Gaussian blur.* A blur of radius

         σ(p) = σ_max · (1 - p)^δ                       (δ = 1.3)

     is applied to the upsampled image. ``σ_max = 18`` px. The gentler
     exponent vs pixelation gives a smoother low-frequency haze that
     fades out before the round ends.

Together these compose ``Reveal(p) = blur( upsample(downsample(I, f_pix), I.size), σ )``.

Why two transforms instead of one
---------------------------------
Pixelation alone produces blocky, often guessable silhouettes for iconic
covers (famous albums are recognised by the colour palette of the largest
super-pixels). Adding a Gaussian blur destroys those low-frequency cues
without making the image unrecoverable: the high-frequency detail returns
as ``p → 1``.

References for parameter choices
--------------------------------
The exponents were tuned by hand against a sample of 50 covers; see
``docs/reveal_math.md`` for the calibration and a comparison plot.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

from PIL import Image, ImageFilter

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RevealParams:
    """Tunable parameters of the reveal transform."""

    f_max: int = 24
    f_min: int = 1
    pix_gamma: float = 1.7
    sigma_max: float = 18.0
    blur_delta: float = 1.3
    output_size: int = 512


DEFAULT = RevealParams()


def reveal_image(
    image: Image.Image, progress: float, params: RevealParams = DEFAULT
) -> Image.Image:
    """Apply the progressive-reveal transform.

    Parameters
    ----------
    image
        Source RGB image (any size; will be resampled to ``params.output_size``).
    progress
        Round progress ``p ∈ [0, 1]``. Values outside the range are clamped.
    """
    p = max(0.0, min(1.0, progress))
    target = (params.output_size, params.output_size)

    base = image.convert("RGB")
    if base.size != target:
        base = base.resize(target, Image.Resampling.LANCZOS)

    # 1. Pixelation factor.
    f_pix = round(params.f_max * (1.0 - p) ** params.pix_gamma + params.f_min)
    f_pix = max(params.f_min, f_pix)

    if f_pix > 1:
        # Downsample to size//f_pix, then nearest-neighbour back up.
        small = base.resize(
            (target[0] // f_pix, target[1] // f_pix), Image.Resampling.BILINEAR
        )
        pixelated = small.resize(target, Image.Resampling.NEAREST)
    else:
        pixelated = base

    # 2. Gaussian blur.
    sigma = params.sigma_max * (1.0 - p) ** params.blur_delta
    blurred = (
        pixelated.filter(ImageFilter.GaussianBlur(radius=sigma)) if sigma > 0.5 else pixelated
    )

    return blurred


def reveal_to_jpeg_bytes(
    image: Image.Image, progress: float, params: RevealParams = DEFAULT, *, quality: int = 80
) -> bytes:
    """Same as :func:`reveal_image` but returns JPEG bytes ready to ship over
    HTTP. JPEG is preferred over PNG for cover art because the residual blur
    and pixelation are smooth gradients that JPEG compresses ~10× tighter."""
    out = reveal_image(image, progress, params)
    buf = io.BytesIO()
    out.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()
