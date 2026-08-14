"""Port of `AI/FrameQuality.swift`.

Heuristic: is this frame essentially blank/uniform — i.e. there is nothing for the AI to see?

A failed capture, a capture-protected window (`SetWindowDisplayAffinity`/DRM), or a solid wallpaper
can come back as a near-uniform frame. In those cases we cannot verify the content, so the caller
handles it as "can't see" (alert, never a hard block). Thresholds are identical to the Mac/Android
versions.
"""


def sample_luminance(image) -> list:
    """Coarse 32x32 grid sample of luminance (0...255) from a PIL image."""
    w, h = image.size
    if w <= 0 or h <= 0:
        return []
    cols, rows = min(32, w), min(32, h)
    small = image.convert("RGB").resize((cols, rows))
    return [(r * 299 + g * 587 + b * 114) // 1000 for (r, g, b) in small.getdata()]


def is_unreadable_luminance(lums) -> bool:
    """Pure heuristic over sampled luminance values (0...255). Extracted so it is unit-testable."""
    if not lums:
        return True
    near_black = 0
    total = 0
    total_sq = 0
    for lum in lums:
        if lum < 16:
            near_black += 1
        total += lum
        total_sq += lum * lum
    n = float(len(lums))
    mean = total / n
    variance = total_sq / n - mean * mean
    black_fraction = near_black / n
    return black_fraction > 0.995 or variance < 4.0


def is_unreadable(image) -> bool:
    return is_unreadable_luminance(sample_luminance(image))
