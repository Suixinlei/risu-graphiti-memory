"""Generic narrative/roleplay ontology for entity extraction.

Card-agnostic by design: no character names, no per-card fields. Types are
described bilingually so the extraction LLM handles Chinese and English
narratives equally well.

NOTE: custom entity types MUST subclass plain pydantic BaseModel, NOT
EntityNode — graphiti's validator rejects any field name that collides with
EntityNode's own (uuid, name, summary, attributes, ...), which subclassing
would always trigger. Graphiti merges these models with EntityNode internally.
Keep all custom fields OPTIONAL: required fields make extraction fail
whole-episode when the LLM omits one.
"""

from typing import Optional

from pydantic import BaseModel, Field


class Character(BaseModel):
    """角色 / Character — a person (or personified being) in the story."""

    role: Optional[str] = Field(
        default=None,
        description='Narrative role: protagonist / supporting / background / user_persona.',
    )
    identity: Optional[str] = Field(
        default=None, description='One-line trait or identity, in the language of the story.'
    )


class Location(BaseModel):
    """地点 / Location — a place where events happen."""

    kind: Optional[str] = Field(default=None, description='e.g. school, city, room, building')


class Item(BaseModel):
    """物品 / Item — a physical object that matters to the plot (gift, weapon, key...)."""

    kind: Optional[str] = Field(default=None, description='e.g. gift, food, document, device')


class Event(BaseModel):
    """事件 / Event — a significant thing that happened in the story."""

    participants: Optional[str] = Field(
        default=None, description='Characters involved, comma-separated.'
    )
    outcome: Optional[str] = Field(
        default=None, description='Result or consequence of the event, if stated.'
    )


class Organization(BaseModel):
    """组织 / Organization — group, faction, club, family, class, company."""

    kind: Optional[str] = Field(default=None, description='e.g. club, class, family, faction')


class Concept(BaseModel):
    """概念 / Concept — abstract notions: promises, secrets, rules, feelings, goals."""

    kind: Optional[str] = Field(default=None, description='e.g. promise, secret, rule, goal')


ENTITY_TYPES: dict[str, type] = {
    'Character': Character,
    'Location': Location,
    'Item': Item,
    'Event': Event,
    'Organization': Organization,
    'Concept': Concept,
}

# Injected into every extraction call. Bilingual, focused on what this memory
# layer is FOR: tracking how relationships/attributes change and what happened.
EXTRACTION_INSTRUCTIONS = """
The narrative is primarily Chinese (may mix English). Extract entities and facts accordingly:
- Prefer the character's canonical name as used in the text; include the full name if given.
- Facts about relationships, feelings, status, promises, or attribute changes are the MOST
  valuable — capture them precisely, including direction and magnitude (e.g. affection
  rose/deepened, became estranged, promised to meet).
- Discrete events worth remembering: meetings, gifts, conflicts, revelations, agreements,
  schedule changes. Skip routine filler actions.
- Reference times stated in the story (dates, "next day", class periods) belong in facts
  when present. If the episode body starts with a 【剧情时间】 header, date facts on that
  in-story calendar (e.g. "4月21日 12:15"), NOT real-world time.
"""
