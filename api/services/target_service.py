from sqlalchemy.dialects.postgresql import insert
from api.commands import TargetCommand
from api.models.db import ExerciseTarget, ExerciseTaxonomy
from api.services.audit_service import audit


async def set_target(db, user_id, payload):
    command = TargetCommand.model_validate(payload)
    if await db.get(ExerciseTaxonomy, command.exercise_name) is None:
        raise ValueError("Unknown exercise")
    data = command.model_dump()
    await db.execute(insert(ExerciseTarget).values(user_id=user_id, **data).on_conflict_do_update(
        index_elements=["user_id", "exercise_name"], set_={k: v for k, v in data.items() if k != "exercise_name"}))
    audit(db, user_id, "set_target", {"exercise_name": command.exercise_name})
