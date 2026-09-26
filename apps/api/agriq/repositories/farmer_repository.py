"""Ownership-scoped repositories for farmer data (Phase 1).

Every read of a farmer-owned resource goes through a ``get_owned``-style
method that joins back to the owning ``farmer_profile``/``user``. A resource
owned by somebody else is indistinguishable from a missing one (404) so the
API never leaks the existence of other farmers' records.
"""
from __future__ import annotations

from typing import Any, Optional

from ..extensions import db
from ..models.farmer import (
    Conversation,
    CropCycle,
    FarmerAction,
    FarmerProfile,
    Farm,
    Field,
    FieldObservation,
    Message,
    Recommendation,
    SoilTest,
)


class ProfileRepository:
    """farmer_profiles data access (one per user)."""

    @staticmethod
    def get_for_user(user_id: int) -> Optional[FarmerProfile]:
        return db.session.execute(
            db.select(FarmerProfile).where(FarmerProfile.user_id == user_id)
        ).scalar_one_or_none()

    @staticmethod
    def create_for_user(user_id: int, data: dict[str, Any]) -> FarmerProfile:
        profile = FarmerProfile(user_id=user_id, **data)
        db.session.add(profile)
        db.session.commit()
        return profile

    @staticmethod
    def update(profile: FarmerProfile, data: dict[str, Any]) -> FarmerProfile:
        for key, value in data.items():
            setattr(profile, key, value)
        db.session.commit()
        return profile


class FarmRepository:
    """farms data access scoped by owner profile."""

    @staticmethod
    def list_for_profile(profile_id: int, include_archived: bool = False) -> list[Farm]:
        stmt = db.select(Farm).where(Farm.farmer_profile_id == profile_id)
        if not include_archived:
            stmt = stmt.where(Farm.archived_at.is_(None))
        stmt = stmt.order_by(Farm.created_at.desc())
        return list(db.session.execute(stmt).scalars())

    @staticmethod
    def get_owned(farm_id: int, profile_id: int) -> Optional[Farm]:
        """Return the farm only when it belongs to this profile."""
        farm = db.session.get(Farm, farm_id)
        if farm is None or farm.farmer_profile_id != profile_id:
            return None
        return farm

    @staticmethod
    def create(profile_id: int, data: dict[str, Any]) -> Farm:
        farm = Farm(farmer_profile_id=profile_id, **data)
        db.session.add(farm)
        db.session.commit()
        return farm

    @staticmethod
    def update(farm: Farm, data: dict[str, Any]) -> Farm:
        for key, value in data.items():
            setattr(farm, key, value)
        db.session.commit()
        return farm

    @staticmethod
    def archive(farm: Farm) -> Farm:
        from ..core.time import utc_now

        farm.archived_at = utc_now()
        db.session.commit()
        return farm


class FieldRepository:
    """fields data access scoped through the owning farm."""

    @staticmethod
    def list_for_farm(farm_id: int, include_archived: bool = False) -> list[Field]:
        stmt = db.select(Field).where(Field.farm_id == farm_id)
        if not include_archived:
            stmt = stmt.where(Field.archived_at.is_(None))
        stmt = stmt.order_by(Field.created_at.asc())
        return list(db.session.execute(stmt).scalars())

    @staticmethod
    def get_owned(field_id: int, profile_id: int) -> Optional[Field]:
        """Return the field only when its farm belongs to this profile."""
        row = db.session.execute(
            db.select(Field)
            .join(Farm, Field.farm_id == Farm.id)
            .where(Field.id == field_id, Farm.farmer_profile_id == profile_id)
        ).scalar_one_or_none()
        return row

    @staticmethod
    def create(farm_id: int, data: dict[str, Any]) -> Field:
        field = Field(farm_id=farm_id, **data)
        db.session.add(field)
        db.session.commit()
        return field

    @staticmethod
    def update(field: Field, data: dict[str, Any]) -> Field:
        for key, value in data.items():
            setattr(field, key, value)
        db.session.commit()
        return field

    @staticmethod
    def archive(field: Field) -> Field:
        from ..core.time import utc_now

        field.archived_at = utc_now()
        db.session.commit()
        return field


class SoilTestRepository:
    """soil_tests data access scoped through field → farm."""

    @staticmethod
    def list_for_field(field_id: int) -> list[SoilTest]:
        stmt = (
            db.select(SoilTest)
            .where(SoilTest.field_id == field_id)
            .order_by(SoilTest.created_at.desc())
        )
        return list(db.session.execute(stmt).scalars())

    @staticmethod
    def get_owned(soil_test_id: int, profile_id: int) -> Optional[SoilTest]:
        row = db.session.execute(
            db.select(SoilTest)
            .join(Field, SoilTest.field_id == Field.id)
            .join(Farm, Field.farm_id == Farm.id)
            .where(SoilTest.id == soil_test_id, Farm.farmer_profile_id == profile_id)
        ).scalar_one_or_none()
        return row

    @staticmethod
    def create(field_id: int, data: dict[str, Any]) -> SoilTest:
        record = SoilTest(field_id=field_id, **data)
        db.session.add(record)
        db.session.commit()
        return record


class CropCycleRepository:
    """crop_cycles data access scoped through field → farm."""

    @staticmethod
    def list_for_field(field_id: int, include_archived: bool = False) -> list[CropCycle]:
        stmt = db.select(CropCycle).where(CropCycle.field_id == field_id)
        if not include_archived:
            stmt = stmt.where(CropCycle.archived_at.is_(None))
        stmt = stmt.order_by(CropCycle.created_at.desc())
        return list(db.session.execute(stmt).scalars())

    @staticmethod
    def get_owned(cycle_id: int, profile_id: int) -> Optional[CropCycle]:
        row = db.session.execute(
            db.select(CropCycle)
            .join(Field, CropCycle.field_id == Field.id)
            .join(Farm, Field.farm_id == Farm.id)
            .where(CropCycle.id == cycle_id, Farm.farmer_profile_id == profile_id)
        ).scalar_one_or_none()
        return row

    @staticmethod
    def active_cycle_for_field(field_id: int) -> Optional[CropCycle]:
        row = db.session.execute(
            db.select(CropCycle)
            .where(
                CropCycle.field_id == field_id,
                CropCycle.status == CropCycle.STATUS_ACTIVE,
                CropCycle.archived_at.is_(None),
            )
            .order_by(CropCycle.created_at.desc())
        ).scalar_one_or_none()
        return row

    @staticmethod
    def create(field_id: int, data: dict[str, Any]) -> CropCycle:
        cycle = CropCycle(field_id=field_id, **data)
        db.session.add(cycle)
        db.session.commit()
        return cycle

    @staticmethod
    def update(cycle: CropCycle, data: dict[str, Any]) -> CropCycle:
        for key, value in data.items():
            setattr(cycle, key, value)
        db.session.commit()
        return cycle

    @staticmethod
    def archive(cycle: CropCycle) -> CropCycle:
        from ..core.time import utc_now

        cycle.archived_at = utc_now()
        cycle.status = CropCycle.STATUS_ARCHIVED
        db.session.commit()
        return cycle


class ObservationRepository:
    """field_observations data access scoped through crop cycle → field → farm."""

    @staticmethod
    def list_for_cycle(cycle_id: int) -> list[FieldObservation]:
        stmt = (
            db.select(FieldObservation)
            .where(FieldObservation.crop_cycle_id == cycle_id)
            .order_by(FieldObservation.observed_at.desc())
        )
        return list(db.session.execute(stmt).scalars())

    @staticmethod
    def create(cycle_id: int, data: dict[str, Any]) -> FieldObservation:
        observation = FieldObservation(crop_cycle_id=cycle_id, **data)
        db.session.add(observation)
        db.session.commit()
        return observation


class ConversationRepository:
    """conversations + messages data access scoped by user."""

    @staticmethod
    def get_or_create(user_id: int, mode: str) -> Conversation:
        conversation = db.session.execute(
            db.select(Conversation)
            .where(Conversation.user_id == user_id, Conversation.mode == mode)
            .order_by(Conversation.updated_at.desc())
        ).scalars().first()
        if conversation is None:
            conversation = Conversation(user_id=user_id, mode=mode)
            db.session.add(conversation)
            db.session.commit()
        return conversation

    @staticmethod
    def add_message(conversation_id: int, role: str, content: str, sources: dict[str, Any] | None = None) -> Message:
        import json

        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            sources_json=json.dumps(sources, ensure_ascii=False) if sources else None,
        )
        db.session.add(message)
        db.session.commit()
        return message

    @staticmethod
    def recent_messages(conversation_id: int, limit: int = 10) -> list[Message]:
        stmt = (
            db.select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        return list(reversed(db.session.execute(stmt).scalars().all()))


class RecommendationRepository:
    """recommendations + farmer_actions data access scoped by user."""

    @staticmethod
    def create(user_id: int, data: dict[str, Any]) -> Recommendation:
        recommendation = Recommendation(user_id=user_id, **data)
        db.session.add(recommendation)
        db.session.commit()
        return recommendation

    @staticmethod
    def add_action(recommendation_id: int, data: dict[str, Any]) -> FarmerAction:
        action = FarmerAction(recommendation_id=recommendation_id, **data)
        db.session.add(action)
        db.session.commit()
        return action


__all__ = [
    "ProfileRepository",
    "FarmRepository",
    "FieldRepository",
    "SoilTestRepository",
    "CropCycleRepository",
    "ObservationRepository",
    "ConversationRepository",
    "RecommendationRepository",
]
