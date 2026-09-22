"""Farmer data model: profile, farms, fields, soil tests, crop cycles,
observations, weather snapshots, market records, conversations, messages,
recommendations and farmer actions (Phase 1 schema).

Storage rules enforced at the model level:
- Timestamps are stored as naive UTC (SQLite-compatible); core.time.as_utc
  normalises to timezone-aware UTC at service/API boundaries.
- Soil values are individually nullable — missing values stay unknown.
- Weather/market rows always carry provider, retrieval time and source.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from .user import User
from ..extensions import db


def _utcnow() -> datetime:
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# Farmer profile
# ---------------------------------------------------------------------------

class FarmerProfile(db.Model):
    """One-to-one farmer profile extending a user account."""

    __tablename__ = "farmer_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(150), nullable=True)
    preferred_language = db.Column(db.String(30), nullable=True)
    state = db.Column(db.String(80), nullable=True)
    district = db.Column(db.String(80), nullable=True)
    village = db.Column(db.String(120), nullable=True)
    consent_version = db.Column(db.String(20), nullable=True)
    consented_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    user = db.relationship("User", backref=db.backref("farmer_profile", uselist=False))
    farms = db.relationship("Farm", back_populates="farmer_profile", lazy="dynamic")


# ---------------------------------------------------------------------------
# Farms and fields
# ---------------------------------------------------------------------------

class Farm(db.Model):
    """A farm owned by exactly one farmer profile."""

    __tablename__ = "farms"

    id = db.Column(db.Integer, primary_key=True)
    farmer_profile_id = db.Column(db.Integer, db.ForeignKey("farmer_profiles.id"), nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False)
    state = db.Column(db.String(80), nullable=True)
    district = db.Column(db.String(80), nullable=True)
    village = db.Column(db.String(120), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    total_area = db.Column(db.Float, nullable=True)
    area_unit = db.Column(db.String(20), nullable=True)
    ownership_type = db.Column(db.String(40), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    archived_at = db.Column(db.DateTime(timezone=True), nullable=True)

    farmer_profile = db.relationship("FarmerProfile", back_populates="farms")
    fields = db.relationship("Field", back_populates="farm", lazy="dynamic")


class Field(db.Model):
    """A managed field inside a farm."""

    __tablename__ = "fields"

    id = db.Column(db.Integer, primary_key=True)
    farm_id = db.Column(db.Integer, db.ForeignKey("farms.id"), nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False)
    area = db.Column(db.Float, nullable=True)
    area_unit = db.Column(db.String(20), nullable=True)
    soil_type = db.Column(db.String(80), nullable=True)
    irrigation_type = db.Column(db.String(80), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    archived_at = db.Column(db.DateTime(timezone=True), nullable=True)

    farm = db.relationship("Farm", back_populates="fields")
    soil_tests = db.relationship("SoilTest", back_populates="field", lazy="dynamic")
    crop_cycles = db.relationship("CropCycle", back_populates="field", lazy="dynamic")
    weather_snapshots = db.relationship("WeatherSnapshot", back_populates="field", lazy="dynamic")


# ---------------------------------------------------------------------------
# Soil tests
# ---------------------------------------------------------------------------

class SoilTest(db.Model):
    """A soil record for a field.

    ``source_type`` is one of: laboratory_report, farmer_entered,
    geospatial_dataset, district_reference. Every numeric value is nullable;
    missing values are unknown and never generated.
    """

    __tablename__ = "soil_tests"

    id = db.Column(db.Integer, primary_key=True)
    field_id = db.Column(db.Integer, db.ForeignKey("fields.id"), nullable=False, index=True)
    tested_at = db.Column(db.DateTime(timezone=True), nullable=True)
    laboratory_name = db.Column(db.String(150), nullable=True)
    report_reference = db.Column(db.String(150), nullable=True)
    ph = db.Column(db.Float, nullable=True)
    electrical_conductivity = db.Column(db.Float, nullable=True)
    organic_carbon = db.Column(db.Float, nullable=True)
    nitrogen = db.Column(db.Float, nullable=True)
    phosphorus = db.Column(db.Float, nullable=True)
    potassium = db.Column(db.Float, nullable=True)
    source_type = db.Column(db.String(40), nullable=False, default="farmer_entered")
    document_path = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    field = db.relationship("Field", back_populates="soil_tests")


# ---------------------------------------------------------------------------
# Crop cycles
# ---------------------------------------------------------------------------

class CropCycle(db.Model):
    """One crop grown on one field across a season."""

    __tablename__ = "crop_cycles"

    STATUS_PLANNED = "planned"
    STATUS_ACTIVE = "active"
    STATUS_HARVESTED = "harvested"
    STATUS_FAILED = "failed"
    STATUS_ARCHIVED = "archived"
    STATUSES = {STATUS_PLANNED, STATUS_ACTIVE, STATUS_HARVESTED, STATUS_FAILED, STATUS_ARCHIVED}

    id = db.Column(db.Integer, primary_key=True)
    field_id = db.Column(db.Integer, db.ForeignKey("fields.id"), nullable=False, index=True)
    crop_name = db.Column(db.String(100), nullable=False)
    variety = db.Column(db.String(100), nullable=True)
    season = db.Column(db.String(40), nullable=True)
    sowing_date = db.Column(db.Date, nullable=True)
    transplanting_date = db.Column(db.Date, nullable=True)
    expected_harvest_date = db.Column(db.Date, nullable=True)
    farmer_confirmed_stage = db.Column(db.String(80), nullable=True)
    calculated_stage = db.Column(db.String(80), nullable=True)
    stage_confirmed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    status = db.Column(db.String(20), nullable=False, default=STATUS_ACTIVE)
    previous_crop = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    archived_at = db.Column(db.DateTime(timezone=True), nullable=True)

    field = db.relationship("Field", back_populates="crop_cycles")
    observations = db.relationship("FieldObservation", back_populates="crop_cycle", lazy="dynamic")


# ---------------------------------------------------------------------------
# Field observations
# ---------------------------------------------------------------------------

class FieldObservation(db.Model):
    """A farmer-recorded field observation on a crop cycle."""

    __tablename__ = "field_observations"

    TYPE_GENERAL = "general"
    TYPE_PEST = "pest"
    TYPE_DISEASE = "disease_symptom"
    TYPE_NUTRIENT = "nutrient_symptom"
    TYPE_IRRIGATION = "irrigation"
    TYPE_WEATHER_DAMAGE = "weather_damage"
    TYPE_GROWTH = "growth_update"
    TYPE_HARVEST = "harvest_update"
    TYPES = {
        TYPE_GENERAL, TYPE_PEST, TYPE_DISEASE, TYPE_NUTRIENT,
        TYPE_IRRIGATION, TYPE_WEATHER_DAMAGE, TYPE_GROWTH, TYPE_HARVEST,
    }

    id = db.Column(db.Integer, primary_key=True)
    crop_cycle_id = db.Column(db.Integer, db.ForeignKey("crop_cycles.id"), nullable=False, index=True)
    observed_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    observation_type = db.Column(db.String(40), nullable=False, default=TYPE_GENERAL)
    field_condition = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    image_path = db.Column(db.String(500), nullable=True)
    farmer_reported_severity = db.Column(db.String(30), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    crop_cycle = db.relationship("CropCycle", back_populates="observations")


# ---------------------------------------------------------------------------
# Provider data snapshots
# ---------------------------------------------------------------------------

class WeatherSnapshot(db.Model):
    """A verified weather observation fetched from Open-Meteo.

    Only provider-returned values are stored; ``is_live`` distinguishes
    live responses from cached responses. Missing values stay NULL.
    """

    __tablename__ = "weather_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    field_id = db.Column(db.Integer, db.ForeignKey("fields.id"), nullable=False, index=True)
    provider = db.Column(db.String(60), nullable=False, default="Open-Meteo")
    provider_observed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    retrieved_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    temperature = db.Column(db.Float, nullable=True)
    humidity = db.Column(db.Float, nullable=True)
    precipitation = db.Column(db.Float, nullable=True)
    rain = db.Column(db.Float, nullable=True)
    wind_speed = db.Column(db.Float, nullable=True)
    weather_code = db.Column(db.Integer, nullable=True)
    raw_response_hash = db.Column(db.String(64), nullable=True)
    is_live = db.Column(db.Boolean, nullable=False, default=True)

    field = db.relationship("Field", back_populates="weather_snapshots")


class MarketPriceRecord(db.Model):
    """An official mandi price record exactly as returned by AGMARKNET."""

    __tablename__ = "market_price_records"

    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(120), nullable=False, default="AGMARKNET via data.gov.in")
    state = db.Column(db.String(80), nullable=True)
    district = db.Column(db.String(80), nullable=True)
    market = db.Column(db.String(120), nullable=True)
    commodity = db.Column(db.String(120), nullable=False)
    variety = db.Column(db.String(120), nullable=True)
    arrival_date = db.Column(db.Date, nullable=True)
    minimum_price = db.Column(db.Float, nullable=True)
    maximum_price = db.Column(db.Float, nullable=True)
    modal_price = db.Column(db.Float, nullable=True)
    retrieved_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    raw_record_hash = db.Column(db.String(64), nullable=True)

    __table_args__ = (
        db.UniqueConstraint(
            "source", "state", "district", "market", "commodity", "variety",
            "arrival_date", "modal_price",
            name="uq_market_official_record",
        ),
        db.Index("ix_market_commodity_district", "commodity", "district"),
    )


# ---------------------------------------------------------------------------
# Assistant conversations
# ---------------------------------------------------------------------------

class Conversation(db.Model):
    """A farmer or student assistant conversation."""

    __tablename__ = "conversations"

    MODE_FARMER = "farmer"
    MODE_STUDENT = "student"
    MODES = {MODE_FARMER, MODE_STUDENT}

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(32), unique=True, index=True, default=lambda: uuid4().hex)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    mode = db.Column(db.String(20), nullable=False, default=MODE_FARMER)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    user = db.relationship("User")
    messages = db.relationship("Message", back_populates="conversation", lazy="dynamic",
                               order_by="Message.created_at")


class Message(db.Model):
    """One message inside a conversation, with its evidence sources."""

    __tablename__ = "messages"

    ROLE_USER = "user"
    ROLE_ASSISTANT = "assistant"
    ROLE_SYSTEM = "system"
    ROLES = {ROLE_USER, ROLE_ASSISTANT, ROLE_SYSTEM}

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(32), unique=True, index=True, default=lambda: uuid4().hex)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id"), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    sources_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    conversation = db.relationship("Conversation", back_populates="messages")


# ---------------------------------------------------------------------------
# Recommendations and farmer actions
# ---------------------------------------------------------------------------

class Recommendation(db.Model):
    """An evidence-backed recommendation with full provenance."""

    __tablename__ = "recommendations"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    farm_id = db.Column(db.Integer, db.ForeignKey("farms.id"), nullable=True)
    field_id = db.Column(db.Integer, db.ForeignKey("fields.id"), nullable=True)
    crop_cycle_id = db.Column(db.Integer, db.ForeignKey("crop_cycles.id"), nullable=True)
    recommendation_type = db.Column(db.String(60), nullable=False, default="advisory")
    action = db.Column(db.Text, nullable=False)
    reasons_json = db.Column(db.Text, nullable=True)
    evidence_json = db.Column(db.Text, nullable=True)
    confidence = db.Column(db.Float, nullable=True)
    valid_from = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    valid_until = db.Column(db.DateTime(timezone=True), nullable=True)
    requires_expert_confirmation = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    user = db.relationship("User")
    actions = db.relationship("FarmerAction", back_populates="recommendation", lazy="dynamic")


class FarmerAction(db.Model):
    """The farmer's response to a recommendation (feedback loop)."""

    __tablename__ = "farmer_actions"

    STATUS_PLANNED = "planned"
    STATUS_COMPLETED = "completed"
    STATUS_SKIPPED = "skipped"
    STATUS_NEEDS_HELP = "needs_help"
    STATUSES = {STATUS_PLANNED, STATUS_COMPLETED, STATUS_SKIPPED, STATUS_NEEDS_HELP}

    id = db.Column(db.Integer, primary_key=True)
    recommendation_id = db.Column(db.Integer, db.ForeignKey("recommendations.id"), nullable=False, index=True)
    action_status = db.Column(db.String(20), nullable=False, default=STATUS_PLANNED)
    farmer_note = db.Column(db.Text, nullable=True)
    action_taken_at = db.Column(db.DateTime(timezone=True), nullable=True)
    outcome_note = db.Column(db.Text, nullable=True)
    outcome_recorded_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    recommendation = db.relationship("Recommendation", back_populates="actions")


__all__ = [
    "User",
    "FarmerProfile",
    "Farm",
    "Field",
    "SoilTest",
    "CropCycle",
    "FieldObservation",
    "WeatherSnapshot",
    "MarketPriceRecord",
    "Conversation",
    "Message",
    "Recommendation",
    "FarmerAction",
]
