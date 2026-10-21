# -*- coding: utf-8 -*-

"""Shared playback preferences for sites that expose several stream variants."""

import re

import xbmcaddon


QUALITY_LEVELS = (0, 2160, 1080, 720, 480, 360)


def preferred_quality(addon=None):
    try:
        addon = addon or xbmcaddon.Addon()
        index = int(addon.getSetting("global_quality") or "0")
    except Exception:
        index = 0
    return QUALITY_LEVELS[index] if 0 <= index < len(QUALITY_LEVELS) else 0


def quality_from_value(value, fallback=0):
    match = re.search(r"(?<!\d)(2160|1440|1080|960|720|540|480|360|240)(?:p|x|\D|$)", str(value or ""), re.IGNORECASE)
    return int(match.group(1)) if match else int(fallback or 0)


def order_quality_variants(variants, addon=None):
    """Order ``(height, value)`` pairs by the configured quality preference.

    A requested limit prefers the best available variant at or below that
    height. If none exists, the lowest higher-quality fallback remains
    playable rather than failing the video outright.
    """
    clean = []
    seen = set()
    for quality, value in variants or []:
        if not value:
            continue
        try:
            marker = value if hash(value) is not None else repr(value)
        except TypeError:
            marker = repr(value)
        if marker in seen:
            continue
        seen.add(marker)
        try:
            quality = int(quality or 0)
        except (TypeError, ValueError):
            quality = quality_from_value(value)
        clean.append((quality, value))
    if not clean:
        return []
    target = preferred_quality(addon)
    if not target:
        return sorted(clean, key=lambda item: item[0], reverse=True)
    within_target = [item for item in clean if item[0] and item[0] <= target]
    above_target = [item for item in clean if not item[0] or item[0] > target]
    return sorted(within_target, key=lambda item: item[0], reverse=True) + sorted(above_target, key=lambda item: item[0])


def select_quality_variant(variants, addon=None, default=None):
    ordered = order_quality_variants(variants, addon)
    return ordered[0][1] if ordered else default
