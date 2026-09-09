from app.core.errors import ServiceUnavailable
from app.repositories.directory import DirectoryRepository
from app.schemas.lists import (
    ListResponse, PageData, Pagination, PaginationParams, PermissionItem, UserItem,
)


def pagination(params: PaginationParams, total: int) -> Pagination:
    pages = (total + params.page_size - 1) // params.page_size
    return Pagination(page=params.page, page_size=params.page_size, total=total,
                      total_pages=pages, has_next=params.page < pages,
                      has_previous=params.page > 1 and total > 0)


def list_permissions(params: PaginationParams, repo: DirectoryRepository) -> ListResponse[PermissionItem]:
    try:
        result = repo.permissions(params)
        if result.count is None:
            raise ValueError("Missing total")
        return ListResponse(data=PageData(
            items=[PermissionItem.model_validate(row) for row in result.data],
            pagination=pagination(params, result.count),
        ))
    except Exception:
        raise ServiceUnavailable("DIRECTORY_UNAVAILABLE", "Permission list is unavailable.") from None


def list_users(params: PaginationParams, repo: DirectoryRepository) -> ListResponse[UserItem]:
    try:
        result = repo.users(params)
        if result.count is None:
            raise ValueError("Missing total")
        assigned = repo.assigned_permissions([str(row["id"]) for row in result.data])
        items = [
            UserItem(
                **{k: row.get(k) for k in ("id", "email", "created_at", "updated_at")},
                is_active=row.get("isActive") is True,
                is_super_admin=row["is_super_admin"] is True,
                is_first_login=row["is_first_login"] is not False,
                permissions=assigned[str(row["id"])],
            )
            for row in result.data
        ]
        return ListResponse(data=PageData(items=items, pagination=pagination(params, result.count)))
    except Exception:
        raise ServiceUnavailable("DIRECTORY_UNAVAILABLE", "User list is unavailable.") from None

