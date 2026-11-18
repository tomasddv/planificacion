"""Shared commercial command-center presentation; no business logic."""
from pathlib import Path
import base64

import streamlit as st

PALETTE = dict(background="#F3F7FC", panel="#FFFFFF", cyan="#145CFF",
               violet="#9333EA", text="#101828", muted="#475467")


def apply_theme():
    st.markdown((Path(__file__).parent / "command_theme.css").read_text(encoding="utf-8"), unsafe_allow_html=True)
    st.markdown((Path(__file__).parent / "planner_color.css").read_text(encoding="utf-8"), unsafe_allow_html=True)
    asset = Path(__file__).parent / "distribuidora_del_valle_truck.png"
    if asset.exists():
        encoded = base64.b64encode(asset.read_bytes()).decode("ascii")
        st.markdown(f'<style>.hero {{background-image:url("data:image/png;base64,{encoded}")!important;}}</style>', unsafe_allow_html=True)


def style_chart(fig):
    fig.update_layout(paper_bgcolor=PALETTE["background"], plot_bgcolor=PALETTE["panel"],
                      font=dict(color=PALETTE["text"], family="Inter, Segoe UI, sans-serif"),
                      colorway=[PALETTE["cyan"], PALETTE["violet"], "#00BFCB", "#56B4D3"],
                      hoverlabel=dict(bgcolor=PALETTE["panel"], font_color=PALETTE["text"]))
    fig.update_xaxes(gridcolor="#E4EAF3", zerolinecolor="#E4EAF3", color=PALETTE["muted"], tickfont_color=PALETTE["muted"], title_font_color=PALETTE["muted"])
    fig.update_yaxes(gridcolor="#E4EAF3", zerolinecolor="#E4EAF3", color=PALETTE["muted"], tickfont_color=PALETTE["muted"], title_font_color=PALETTE["muted"])
    fig.update_layout(legend_font_color=PALETTE["text"])
    return fig
