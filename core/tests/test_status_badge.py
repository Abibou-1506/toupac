"""Tests du helper render_status_badge (core/admin.py)."""
from core.admin import STATUS_COLOR_MAP, render_status_badge


def test_renders_mapped_status_with_right_color_class():
    """Un statut connu produit la classe de couleur mappée."""
    html = render_status_badge("delivered", "Livré")
    assert "bg-success-50" in html
    assert "text-success-600" in html
    assert "Livré" in html


def test_falls_back_to_base_for_unknown_status():
    """Un statut non mappé tombe sur base (gris), ne crashe pas."""
    html = render_status_badge("some_new_status", "Nouveau")
    assert "bg-base-50" in html
    assert "text-base-600" in html


def test_returns_dash_for_none_value():
    """Un None affiche un tiret, pas un badge vide."""
    assert render_status_badge(None, "") == "—"


def test_status_color_map_covers_all_business_terminals():
    """Garde-fou : les statuts terminaux critiques sont tous mappés.

    Si un statut critique disparaît du mapping par oubli, ce test échoue
    avant que les admins ne se mettent à afficher du gris en production.
    """
    required = {
        "delivered", "paid", "resolved",  # success
        "in_transit", "pending",           # warning
        "failed", "cancelled",              # danger
        "draft", "scheduled",               # primary
    }
    assert required.issubset(STATUS_COLOR_MAP.keys())
