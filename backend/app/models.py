from pydantic import model_validator
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict


class DocumentVersion(str, Enum):
    earlier = "earlier"
    later = "later"


class ConfidenceLevel(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class ChangeType(str, Enum):
    added = "added"
    removed = "removed"
    modified = "modified"
    clarification = "clarification"
    deadline = "deadline"
    eligibility = "eligibility"
    process = "process"
    fee = "fee"
    document_requirement = "document_requirement"
    other = "other"


class ChangeDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(description="Short factual heading for the detected policy change.")
    change_type: ChangeType
    old_text: str = Field(description="Short excerpt from the earlier version; empty for a purely added provision.")
    new_text: str = Field(description="Short excerpt from the later version; empty for a purely removed provision.")
    explanation: str = Field(description="Plain-language description of exactly what changed. Do not speculate.")
    affected_stakeholders: list[str] = Field(description="Groups explicitly affected or plausibly affected; qualify uncertainty.")
    practical_action: str = Field(description="A cautious next step, or state that no action is established by the documents.")
    old_page: int | None = Field(description="1-based PDF page in the earlier document, or null if no old evidence applies.")
    old_quote: str = Field(description="A short verbatim supporting quote from that exact earlier PDF page; empty if not applicable.")
    new_page: int | None = Field(description="1-based PDF page in the later document, or null if no new evidence applies.")
    new_quote: str = Field(description="A short verbatim supporting quote from that exact later PDF page; empty if not applicable.")
    confidence: ConfidenceLevel = Field(description="Confidence based on the clarity of the cited source evidence.")
    review_required: bool = Field(description="True when interpretation, legal effect, conflict, or evidence needs human review.")
    pairing_verification: dict[str, Any] | None = Field(default=None, description="Backend assessment of whether old/new excerpts discuss the same policy provision.")
    addition_verification: dict[str, Any] | None = Field(default=None, description="Full-earlier-document search for a corresponding provision when a change is a candidate addition.")
    removal_verification: dict[str, Any] | None = Field(default=None, description="Full-later-document search for a corresponding provision when a change is a candidate removal.")

    @model_validator(mode="after")
    def _force_review_for_removed_change(self):
        change_type = getattr(self.change_type, "value", self.change_type)
        if str(change_type).casefold() == "removed":
            object.__setattr__(self, "review_required", True)
        return self


class ActionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str
    reason: str
    source_document: Literal["earlier", "later", "none"] = Field(description="Exactly one of earlier, later, or none. Never put a filename, document title, page description, or explanation here.")
    source_page: int | None
    review_required: bool


class ComparisonDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_title: str
    executive_summary: str
    key_findings: list[str]
    changes: list[ChangeDraft]
    action_checklist: list[ActionDraft]
    limitations: list[str]
    overall_review_required: bool
    candidate_review_metadata: dict[str, Any] = Field(default_factory=dict, description="Actual candidate review coverage and batch execution metadata.")

    @model_validator(mode="after")
    def _propagate_review_to_comparison(self):
        changes = getattr(self, "changes", []) or []
        requires_review = any(
            bool(getattr(item, "review_required", False))
            or str(getattr(getattr(item, "change_type", ""), "value",
                           getattr(item, "change_type", ""))).casefold() == "removed"
            for item in changes
        )
        if requires_review:
            object.__setattr__(self, "overall_review_required", True)
        return self


class CompareRequest(BaseModel):
    earlier_document_id: str
    later_document_id: str


class UploadResponse(BaseModel):
    document_id: str
    filename: str
    version: DocumentVersion
    title: str
    page_count: int
    extracted_characters: int
    created_at: str
    file_size_bytes: int = 0
    sha256: str = ""
    nonempty_pages: int = 0
    empty_pages: list[int] = Field(default_factory=list)
    pdf_metadata: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class DocumentListItem(BaseModel):
    document_id: str
    filename: str
    version: DocumentVersion
    title: str
    page_count: int
    extracted_characters: int
    created_at: str
    file_size_bytes: int = 0
    sha256: str = ""
    nonempty_pages: int = 0
    empty_pages: list[int] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DocumentPageResponse(BaseModel):
    document_id: str
    page: int
    character_count: int
    has_text: bool
    text: str


class CompareResponse(BaseModel):
    analysis_id: str
    status: str
    message: str


class ErrorResponse(BaseModel):
    detail: str
