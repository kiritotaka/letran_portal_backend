from dataclasses import dataclass
from app.core.errors import ApiError


@dataclass(frozen=True)
class FilePolicy:
    permission: str
    allowed_types: dict[str, str]
    max_bytes: int = 10 * 1024 * 1024


POLICIES = {
    'product_import': FilePolicy('PRODUCT_IMPORT', {
        '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        '.csv': 'text/csv',
    }),
}


def policy_for(purpose, actor):
    policy = POLICIES.get(purpose)
    if policy is None:
        raise ApiError(422, 'UNSUPPORTED_FILE_PURPOSE', 'Unsupported file purpose.')
    if not actor.is_super_admin and policy.permission not in actor.permissions:
        raise ApiError(403, 'FORBIDDEN', 'Permission is required for this file purpose.')
    return policy
