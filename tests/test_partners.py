import pytest
from fastapi import HTTPException

from firesync import config
from firesync.report import bulletin


def test_partner_urls_are_sanitised():
    from firesync.api.app import _clean_partners
    ok = _clean_partners([{"name": "SENSAT", "url": "", "logo": "/assets/partners/sensat.png", "role": "partner"},
                          {"name": "X", "url": "https://x.org", "logo": "", "role": "weird", "dark": 1}])
    assert ok[0]["role"] == "partner" and ok[1]["role"] == "partner" and ok[1]["dark"] is True
    for bad in ({"name": "a", "url": "javascript:alert(1)"}, {"name": "a", "logo": "data:image/svg+xml,<svg>"},
                {"name": "a", "logo": "/assets/../../secret"}, {"name": ""}):
        with pytest.raises(HTTPException):
            _clean_partners([bad])


def test_default_logos_ship_and_render_in_pdf_header():
    for p in config.DEFAULT_PARTNERS:
        assert (config.WEB / p["logo"].lstrip("/")).exists()
    assert bulletin._header_logos(config.DEFAULT_PARTNERS) is not None
    # paths outside web/ are ignored
    assert bulletin._header_logos([{"logo": "/assets/../../README.md"}]) is None


def test_pdf_symbols_use_a_font_that_has_them():
    s = bulletin._g("▲▲ risque élevé → fin")
    if bulletin.SYM_FONT:
        assert s.count("<font") == 3 and "risque élevé" in s
