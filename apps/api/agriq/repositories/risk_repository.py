"""Ownership-scoped persistence for risk assessments (Phase 5 §28–29).

Append-only by design: a new run supersedes (never deletes) the previous
active run, so risk history is preserved verbatim for audit and evaluation.
"""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Any, Optional

from sqlalchemy import select

from ..extensions import db
from ..models.risk import RiskAssessment


def _dump(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


class RiskAssessmentRepository:
    """Data access for ``risk_assessments`` (owner-scoped reads)."""

    @staticmethod
    def create(user_id: int, data: dict[str, Any]) -> RiskAssessment:
        row = RiskAssessment(user_id=user_id, **data)
        db.session.add(row)
        db.session.commit()
        return row

    @staticmethod
    def get_owned(assessment_id: int, user_id: int) -> Optional[RiskAssessment]:
        """Owner-only fetch: a foreign id is indistinguishable from missing."""
        return db.session.execute(
            select(RiskAssessment).where(
                RiskAssessment.id == assessment_id,
                RiskAssessment.user_id == user_id,
                RiskAssessment.record_status == "active",
            )
        ).scalar_one_or_none()

    @staticmethod
    def active_run_for_field(field_id: int, user_id: int) -> list[RiskAssessment]:
        return list(
            db.session.execute(
                select(RiskAssessment)
                .where(
                    RiskAssessment.field_id == field_id,
                    RiskAssessment.user_id == user_id,
                    RiskAssessment.record_status == "active",
                )
                .order_by(RiskAssessment.id.asc())
            ).scalars()
        )

    @staticmethod
    def recent_complete_run(field_id: int, ttl_minutes: int) -> list[RiskAssessment]:
        """Assessments of the latest run still inside the idempotency window."""
        cutoff = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).replace(tzinfo=None) - timedelta(minutes=ttl_minutes)
        latest = db.session.execute(
            select(RiskAssessment)
            .where(
                RiskAssessment.field_id == field_id,
                RiskAssessment.record_status == "active",
                RiskAssessment.run_group.isnot(None),
            )
            .order_by(RiskAssessment.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if latest is None or (latest.generated_at and latest.generated_at < cutoff):
            return []
        return list(
            db.session.execute(
                select(RiskAssessment)
                .where(
                    RiskAssessment.run_group == latest.run_group,
                    RiskAssessment.record_status == "active",
                )
                .order_by(RiskAssessment.id.asc())
            ).scalars()
        )

    @staticmethod
    def replace_active_run(
        *,
        field_id: int,
        user_id: int,
        farm_id: Optional[int],
        crop_cycle_id: Optional[int],
        assessments: list[dict[str, Any]],
        rule_version: str,
        valid_until: Any,
    ) -> list[RiskAssessment]:
        """Persist a full run: mark the previous run superseded, insert new rows.

        Deduplication (§36): when every new assessment matches its predecessor
        (same risk_type, status, probability and rule_version) the previous run
        is KEPT and no new rows are written — identical warnings are not
        re-created.
        """
        import uuid as _uuid

        previous = RiskAssessmentRepository.active_run_for_field(field_id, user_id)
        prev_by_type = {p.risk_type: p for p in previous}

        unchanged = bool(previous) and len(previous) == len(assessments) and all(
            (p := prev_by_type.get(a["risk_type"])) is not None
            and p.status == a["status"]
            and p.probability == a["probability"]
            and p.rule_version == rule_version
            for a in assessments
        )
        if unchanged:
            return previous

        run_group = _uuid.uuid4().hex
        rows: list[RiskAssessment] = []
        for prev in previous:
            prev.record_status = "superseded"
        for item in assessments:
            data = dict(item)
            evidence = data.pop("evidence", None)
            reasons = data.pop("reasons", None)
            actions = data.pop("actions", None)
            data_quality = data.pop("data_quality", None)
            confidence_basis = data.pop("confidence_basis", None)
            row = RiskAssessment(
                user_id=user_id,
                field_id=field_id,
                farm_id=farm_id,
                crop_cycle_id=crop_cycle_id,
                run_group=run_group,
                reasons_json=_dump(reasons),
                actions_json=_dump(actions),
                evidence_json=_dump(evidence),
                data_quality_json=_dump(data_quality),
                confidence_basis=confidence_basis,
                rule_version=rule_version,
                valid_until=valid_until,
                **data,
            )
            db.session.add(row)
            rows.append(row)
        db.session.commit()
        return rows

    @staticmethod
    def history_for_field(field_id: int, user_id: int, limit: int = 50) -> list[RiskAssessment]:
        """Full append-only history (superseded rows included)."""
        return list(
            db.session.execute(
                select(RiskAssessment)
                .where(RiskAssessment.field_id == field_id, RiskAssessment.user_id == user_id)
                .order_by(RiskAssessment.id.desc())
                .limit(limit)
            ).scalars()
        )


__all__ = ["RiskAssessmentRepository"]
