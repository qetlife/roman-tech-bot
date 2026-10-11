import logging
import uuid

from typing             import Any

from sqlalchemy         import delete, select

from db.db              import SessionLocal
from models.user_setting import UserSetting
from settings.registry  import Setting


logger = logging.getLogger(__name__)


class SettingsRepository:
    def get(self, user_id: uuid.UUID, setting: Setting) -> Any:
        """The user's value, or the default if unset or no longer valid."""
        with SessionLocal() as session:
            row = session.get(UserSetting, (user_id, setting.key))
            return self._value(row, setting)

    def get_for_users(self, user_ids, setting: Setting) -> dict:
        """{user_id: value} for many users at once (defaults included)."""
        user_ids = set(user_ids)
        with SessionLocal() as session:
            rows = session.scalars(
                select(UserSetting).where(UserSetting.key == setting.key, UserSetting.user_id.in_(user_ids))
            )
            stored = {row.user_id: self._value(row, setting) for row in rows}
        return {uid: stored.get(uid, setting.default) for uid in user_ids}

    def set(self, user_id: uuid.UUID, setting: Setting, value: Any) -> Any:
        """Validate and store a value; raises ValueError if invalid."""
        value = setting.validate(value)
        with SessionLocal() as session:
            if value == setting.default:
                # Only differences from the default are stored.
                session.execute(delete(UserSetting).where(
                    UserSetting.user_id == user_id, UserSetting.key == setting.key,
                ))
            else:
                row = session.get(UserSetting, (user_id, setting.key))
                if row is None:
                    session.add(UserSetting(user_id=user_id, key=setting.key, value=value))
                else:
                    row.value = value
            session.commit()
        return value

    def reset(self, user_id: uuid.UUID, setting: Setting) -> Any:
        return self.set(user_id, setting, setting.default)

    @staticmethod
    def _value(row, setting: Setting) -> Any:
        if row is None:
            return setting.default
        try:
            return setting.validate(row.value)
        except ValueError:
            # Stored before the rules changed: fall back rather than break.
            logger.warning("Invalid stored value for %s (user %s); using default", setting.key, row.user_id)
            return setting.default
