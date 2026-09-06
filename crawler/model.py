from typing import Optional

from pydantic import BaseModel, Field


class Provenance(BaseModel):
    origin: str = "crawled"
    source: str
    fetched_at: str
    confidence: str = "auto"


class Facet(BaseModel):
    id: str
    origin: str = "computed"
    confidence: str = "auto"
    evidence: list[str] = Field(default_factory=list)


class Professor(BaseModel):
    slug: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    school: str
    dept: str
    status: str = "roster"
    title: Optional[str] = None
    supervisor: Optional[str] = None
    subjects: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    office_address: Optional[str] = None
    bio_raw: Optional[str] = None
    institutes: list[str] = Field(default_factory=list)
    homepage: Optional[str] = None
    photo_url: Optional[str] = None
    research_direction_raw: Optional[str] = None
    detail_url: str
    profile_url: Optional[str] = None
    first_seen: Optional[str] = None
    last_verified: Optional[str] = None
    source_updated_at: Optional[str] = None
    facets: list[Facet] = Field(default_factory=list)
    provenance: dict[str, Provenance] = Field(default_factory=dict)


class Issue(BaseModel):
    kind: str
    ref: str
    message: str
    first_seen: str
    resolved: bool = False
    # 人工复验标记: True=确认属官网侧问题(死链/字段确缺/外链被墙), preflight 不再报
    reviewed: Optional[bool] = None
    review_note: Optional[str] = None
