"""Shared commercial command-center presentation; no business logic."""
from pathlib import Path

import streamlit as st

PALETTE = dict(background="#080C16", panel="#111A2B", cyan="#26E6FF",
               violet="#8B5CF6", text="#F3F6FC", muted="#A9B7CC")


def apply_theme():
    st.markdown((Path(__file__).parent / "command_theme.css").read_text(encoding="utf-8"), unsafe_allow_html=True)


def style_chart(fig):
    fig.update_layout(paper_bgcolor=PALETTE["background"], plot_bgcolor=PALETTE["panel"],
                      font=dict(color=PALETTE["text"], family="Inter, Segoe UI, sans-serif"),
                      colorway=[PALETTE["cyan"], PALETTE["violet"], "#E2E8F0", "#56B4D3"],
                      hoverlabel=dict(bgcolor=PALETTE["panel"], font_color=PALETTE["text"]))
    fig.update_xaxes(gridcolor="#233149", zerolinecolor="#233149", color=PALETTE["muted"], tickfont_color=PALETTE["muted"], title_font_color=PALETTE["muted"])
    fig.update_yaxes(gridcolor="#233149", zerolinecolor="#233149", color=PALETTE["muted"], tickfont_color=PALETTE["muted"], title_font_color=PALETTE["muted"])
    fig.update_layout(legend_font_color=PALETTE["text"])
    return fig
