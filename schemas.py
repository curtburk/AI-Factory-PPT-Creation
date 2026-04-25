"""
Deck Factory v2 -- Pydantic Schemas
====================================
These models define the deck plan JSON schema. The schema is passed to vLLM's
response_format for constrained decoding via XGrammar. The model physically
cannot produce output that doesn't match these types.
"""

from __future__ import annotations
from typing import Literal, Union
from pydantic import BaseModel, Field


# ── Slide Components ──────────────────────────────────────────────────────────

class Stat(BaseModel):
    value: str
    label: str


class ChartSeries(BaseModel):
    name: str
    values: list[float]


class Chart(BaseModel):
    type: Literal["bar", "line", "pie"]
    labels: list[str]
    series: list[ChartSeries]


class IconItem(BaseModel):
    icon: Literal[
        "shield", "server", "zap", "chart", "users",
        "lock", "globe", "check", "target", "layers"
    ]
    title: str
    description: str


class TwoColumnSide(BaseModel):
    heading: str
    items: list[str]


# ── Slide Types ───────────────────────────────────────────────────────────────

class TitleSlide(BaseModel):
    layout: Literal["title_slide"]
    title: str
    subtitle: str


class SectionDivider(BaseModel):
    layout: Literal["section_divider"]
    title: str


class BulletsSlide(BaseModel):
    layout: Literal["bullets"]
    title: str
    items: list[str]
    speakerNotes: str = ""


class TwoColumn(BaseModel):
    layout: Literal["two_column"]
    title: str
    left: TwoColumnSide
    right: TwoColumnSide
    speakerNotes: str = ""


class StatCallout(BaseModel):
    layout: Literal["stat_callout"]
    title: str
    stats: list[Stat]
    speakerNotes: str = ""


class ChartSlide(BaseModel):
    layout: Literal["chart_slide"]
    title: str
    chart: Chart
    speakerNotes: str = ""


class IconGrid(BaseModel):
    layout: Literal["icon_grid"]
    title: str
    items: list[IconItem]
    speakerNotes: str = ""


class ImageText(BaseModel):
    layout: Literal["image_text"]
    title: str
    text: str
    imagePlaceholder: str
    imagePosition: Literal["left", "right"]
    speakerNotes: str = ""


class ClosingSlide(BaseModel):
    layout: Literal["closing"]
    title: str
    subtitle: str
    contactInfo: str = ""


# ── Deck Plan ─────────────────────────────────────────────────────────────────

class DeckMeta(BaseModel):
    title: str
    author: str
    palette: Literal[
        "midnight_executive", "forest_moss", "coral_energy",
        "warm_terracotta", "ocean_gradient", "charcoal_minimal", "teal_trust"
    ]


# Use a simplified union approach for broader vLLM compatibility.
# Discriminated unions on "layout" may not be supported by all XGrammar versions.
SlideType = Union[
    TitleSlide, SectionDivider, BulletsSlide, TwoColumn,
    StatCallout, ChartSlide, IconGrid, ImageText, ClosingSlide
]


class DeckPlan(BaseModel):
    meta: DeckMeta
    slides: list[SlideType]


def get_deck_schema() -> dict:
    """Return the JSON Schema for DeckPlan, ready to pass to vLLM."""
    return DeckPlan.model_json_schema()
