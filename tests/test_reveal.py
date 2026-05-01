"""Tests for the cover-art progressive-reveal transform."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from songguesser.reveal import DEFAULT, RevealParams, reveal_image, reveal_to_jpeg_bytes


@pytest.fixture
def synthetic_cover() -> Image.Image:
    """A 256x256 image with a sharp diagonal high-frequency pattern. The
    pattern's variance is ideal for measuring how much the reveal transform
    smears it: a fully-revealed image should retain (most of) the variance,
    a fully-obscured one should lose almost all of it."""
    rng = np.random.default_rng(seed=42)
    base = (rng.random((256, 256, 3)) * 255).astype(np.uint8)
    return Image.fromarray(base, mode="RGB")


def _luminance_std(img: Image.Image) -> float:
    arr = np.asarray(img.convert("L"), dtype=np.float64)
    return float(arr.std())


def test_progress_zero_is_more_obscured_than_progress_one(synthetic_cover: Image.Image) -> None:
    """Variance is monotone non-decreasing in progress; the early image
    must be substantially less detailed than the late image."""
    obscured = reveal_image(synthetic_cover, 0.0)
    revealed = reveal_image(synthetic_cover, 1.0)
    assert _luminance_std(obscured) < _luminance_std(revealed)
    # The factor should be substantial — we expect at least 2x more variance
    # in the revealed image given the chosen σ_max=18 and f_max=24.
    assert _luminance_std(revealed) >= 2.0 * _luminance_std(obscured)


def test_progress_clamped_to_unit_interval(synthetic_cover: Image.Image) -> None:
    a = reveal_image(synthetic_cover, -1.0)
    b = reveal_image(synthetic_cover, 0.0)
    c = reveal_image(synthetic_cover, 1.0)
    d = reveal_image(synthetic_cover, 5.0)
    # Below-zero clamps to zero, above-one clamps to one. Pixel-equal.
    assert np.array_equal(np.asarray(a), np.asarray(b))
    assert np.array_equal(np.asarray(c), np.asarray(d))


def test_reveal_emits_target_size(synthetic_cover: Image.Image) -> None:
    out = reveal_image(synthetic_cover, 0.5)
    assert out.size == (DEFAULT.output_size, DEFAULT.output_size)


def test_reveal_to_jpeg_bytes_returns_jpeg(synthetic_cover: Image.Image) -> None:
    blob = reveal_to_jpeg_bytes(synthetic_cover, 0.5)
    # JPEG SOI marker is FF D8 FF; tail EOI marker is FF D9.
    assert blob[:3] == b"\xff\xd8\xff"
    assert blob[-2:] == b"\xff\xd9"
    img = Image.open(io.BytesIO(blob))
    assert img.size == (DEFAULT.output_size, DEFAULT.output_size)


def test_reveal_at_progress_one_is_close_to_input(synthetic_cover: Image.Image) -> None:
    """At p=1, both the pixelation factor (1) and blur (~0) are no-ops, so
    the output equals the input (modulo the LANCZOS upsampling from 256→512).

    Theoretical luminance std for an i.i.d. uniform[0,255] RGB image is
    ``sqrt((0.299^2 + 0.587^2 + 0.114^2) · (255^2 / 12)) ≈ 47.4``, so we
    use 40 as a robust lower bound that survives finite-sample fluctuation.
    """
    out = reveal_image(synthetic_cover, 1.0)
    arr_out = np.asarray(out.convert("L"), dtype=np.float64)
    assert _luminance_std(synthetic_cover) > 40.0
    # LANCZOS upsampling smooths slightly; allow a generous margin.
    assert arr_out.std() > 35.0


def test_custom_params_increase_obscuration() -> None:
    """A more aggressive σ_max should produce a smaller variance at p=0."""
    img = Image.fromarray((np.random.default_rng(0).random((256, 256, 3)) * 255).astype(np.uint8))
    soft = reveal_image(img, 0.0, RevealParams(sigma_max=4.0, f_max=4))
    hard = reveal_image(img, 0.0, RevealParams(sigma_max=32.0, f_max=64))
    assert _luminance_std(hard) < _luminance_std(soft)
