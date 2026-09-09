# User and permission lists

Both endpoints require `Authorization: Bearer <access_token>`. Swagger /docs:
login, copy access_token, click Authorize, paste the token, then execute the list.
Supabase Auth validates it remotely using get_user(token). Each request reloads the
profile and assigned rights. No trust in FE role flags or token user_metadata.

## Access

| Endpoint | Super admin | Ordinary user |
| --- | --- | --- |
| GET /api/v1/users | Allowed | USER_VIEW |
| GET /api/v1/permissions | Allowed | Any of PERM_VIEW, USER_CREATE, USER_UPDATE |

Before these rules, every account must have a profile and is_first_login=false.
Missing/invalid token: 401. Missing profile/rights or required password change: 403.
Upstream auth/database failure: 503 with safe JSON error. No schema writes.
These rules only authorize listing, not creating users or assigning permissions.

## Pagination

`?page=1&page_size=20` on both endpoints.
page: 1..1000000; page_size: 1..100, default 20. Invalid values: 422.
Stable sort by id ascending. total is an exact count under the current query.
Out-of-range page returns items=[] and the requested page, no clamping.
Empty table has total_pages=0. has_previous means a previous nonempty range exists,
not necessarily that page-1 itself is populated for an out-of-range request.
Multiple requests do not form a database snapshot; data changes can shift page boundaries.

## Permissions

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": 9,
        "permission_code": "USER_CREATE",
        "permission_name": "Tạo mới",
        "group_id": 3,
        "group": {"id": 3, "group_name": "Quản lý người dùng", "description": null}
      }
    ],
    "pagination": {"page": 1, "page_size": 20, "total": 1, "total_pages": 1, "has_next": false, "has_previous": false}
  }
}
```

IDs/group names are illustrative. A permission without a group has group_id/group=null.
Flat paginated items avoid splitting/duplicating nested group arrays. FE groups the
loaded items by group.id and places null in an ungrouped section. Fetch every page
using has_next before treating the picker as the full catalog. There is no selected field.

## Users

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "11111111-1111-4111-8111-111111111111",
        "email": "user@example.com",
        "is_super_admin": false,
        "is_first_login": false,
        "created_at": null,
        "updated_at": null,
        "permissions": ["USER_VIEW"]
      }
    ],
    "pagination": {"page": 1, "page_size": 20, "total": 1, "total_pages": 1, "has_next": false, "has_previous": false}
  }
}
```

Lists portal users from profiles, not every auth.users account. Auth-only accounts
without a portal profile are excluded. No password, tokens or Auth metadata returned.
Null is_super_admin is false; null is_first_login is true, consistent with login.
permissions contains sorted, deduplicated assigned codes from user_permissions → permissions.
profiles.permissions is never used. For administrators this is still the assigned
list, not ["*"]; is_super_admin conveys the effective full-access override.
Permission assignments are fetched in batches for users on the requested page,
not one network query per listed user.

## Checkbox mapping

```typescript
const selected = new Set(editingUser ? editingUser.permissions : []);
const options = allPermissionPages.flatMap(page => page.data.items).map(permission => ({
  ...permission,
  selected: selected.has(permission.permission_code),
}));
```

New user: every checkbox starts unchecked. Editing: select only assigned codes.
For super admin, show a separate full-access indication; do not overwrite stored
assignments just because it has full access. Listing a permission does not mean the
caller is authorized to grant it; write APIs must enforce their own rules later.

This release does not change FE, implement add/update/delete user, search/filter,
or add a user detail endpoint. FE can use the listed user's assignments for the
current edit form; reload before editing if the list may be stale.
