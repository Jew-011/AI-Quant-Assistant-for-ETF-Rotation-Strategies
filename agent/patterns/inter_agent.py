"""
Pattern 15: Inter-agent Communication.

Defines the structured message envelope that every specialist agent emits.
Using a pydantic schema guarantees (a) the Coordinator always receives the same
shape, (b) the frontend can visualise each agent's stance and confidence, and
(c) we get a natural audit trail.

The message format is deliberately inspired by the "proposal / evidence / veto
/ vote" vocabulary used in Multi-Agent Debate research papers.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AgentRole(str, Enum):
    QUANT = "quant"
    MACRO = "macro"
    RISK = "risk"
    COORDINATOR = "coordinator"


class Stance(str, Enum):
    OVERWEIGHT = "overweight"   # strong recommend
    NEUTRAL = "neutral"
    UNDERWEIGHT = "underweight"
    VETO = "veto"               # must exclude


class Evidence(BaseModel):
    """A single piece of evidence an agent cites for its stance."""
    source: str = Field(
        description="short label: 'factor_table' | 'news' | 'veto_list' | 'macro_event' | 'research_library'"
    )
    content: str = Field(description="verbatim snippet or numeric summary")
    weight: float = Field(ge=0.0, le=1.0, default=0.5, description="subjective confidence")


class AgentVote(BaseModel):
    """Structured message emitted by a specialist agent for ONE sector."""
    sector: str = Field(description="industry name, e.g. '半导体'")
    stance: Stance = Field(description="proposed action on this sector")
    confidence: float = Field(ge=0.0, le=1.0, description="how strong is this view")
    rationale: str = Field(description="2-3 sentences explaining why")
    evidences: list[Evidence] = Field(
        default_factory=list, description="supporting evidence items"
    )


class AgentReport(BaseModel):
    """All votes from a single specialist agent for the current round."""
    role: AgentRole
    round_index: int = 0
    summary: str = Field(description="one-paragraph overall view of the market")
    votes: list[AgentVote] = Field(
        default_factory=list, description="per-sector recommendations"
    )
    caveats: list[str] = Field(
        default_factory=list, description="known limitations or missing data"
    )


class Disagreement(BaseModel):
    """Coordinator logs a concrete disagreement between specialist agents."""
    sector: str
    agents_pro: list[AgentRole] = Field(default_factory=list)
    agents_con: list[AgentRole] = Field(default_factory=list)
    resolution: str = Field(
        default="",
        description="how the coordinator resolved the conflict (majority / veto / human)",
    )


class DebateVerdict(BaseModel):
    """Coordinator's final output after aggregating all specialist reports."""
    final_stance_per_sector: dict[str, Stance] = Field(default_factory=dict)
    confidence_per_sector: dict[str, float] = Field(default_factory=dict)
    disagreements: list[Disagreement] = Field(default_factory=list)
    narrative: str = Field(description="plain-language rationale for the aggregate view")
    recommended_sectors: list[str] = Field(
        default_factory=list, description="sectors to overweight after debate"
    )
    vetoed_sectors: list[str] = Field(
        default_factory=list, description="sectors excluded by any risk agent veto"
    )
    # reasoning trail (pattern 17): number of self-consistency samples used & the majority choice
    self_consistency: Optional[dict] = None
