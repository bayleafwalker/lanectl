"""Shared stylesheet: WCAG AA contrast, both schemes, and the state vocabulary."""
from lanectl.html_style import HEAD_META, STYLE, TOKENS, badge
from lanectl.vocab import classify


def luminance(hex_):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4
    r, g, b = (int(hex_[i:i + 2], 16) for i in (1, 3, 5))
    return .2126 * lin(r) + .7152 * lin(g) + .0722 * lin(b)


def ratio(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + .05) / (lo + .05)


def test_every_text_token_has_aa_contrast_on_bg_and_surface_in_both_schemes():
    for scheme, tokens in TOKENS.items():
        for name in ("text", "muted", "accent", "ok", "needs", "failed", "running", "idle", "unknown"):
            for ground in ("bg", "surface"):
                assert ratio(tokens[name], tokens[ground]) >= 4.5, (scheme, name, ground)


def test_style_has_dark_scheme_and_head_meta():
    assert "prefers-color-scheme: dark" in STYLE
    assert 'name="viewport"' in HEAD_META


def test_vocabulary_and_badge_carry_symbol_and_word():
    assert [classify(s) for s in ("parked", "failed", "active", "landed", "ready", "weird")] == [
        "needs", "failed", "running", "ok", "idle", "unknown"]
    assert "▲" in badge("parked") and "parked" in badge("parked")
    assert "&lt;" in badge("<b>")
