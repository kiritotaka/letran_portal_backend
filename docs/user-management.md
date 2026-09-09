# Quản trị user

## Cài đặt trước khi dùng

1. Supabase → SQL Editor → New query. Chạy toàn bộ `migrations/001_portal_manage_user.sql` một lần trên đúng project. File chỉ tạo/thay thế một function, cấp EXECUTE cho `service_role`, không thêm table/column và không thay đổi dữ liệu hiện tại.
2. Deploy backend mới lên Render. Có thể chọn Manual Deploy → Deploy latest commit nếu auto deploy chưa chạy.
3. Login bằng super admin đang hoạt động và đã đổi mật khẩu lần đầu. Dùng `access_token` trong Swagger Authorize hoặc header `Authorization: Bearer <access_token>`.

Function cần thiết để cập nhật profile và nhiều dòng `user_permissions` trong cùng transaction. Nếu chưa cài, API ghi trả 503 `USER_MANAGEMENT_NOT_INSTALLED` trước khi tạo Auth user. `profiles."isActive"` phải tồn tại đúng tên; API dùng tên `is_active`.

## API

Base URL: `https://letran-portal-backend.onrender.com/api/v1`.

| Method | Path | Quyền |
| --- | --- | --- |
| POST | `/users` | `USER_CREATE` |
| PATCH | `/users/{user_id}` | `USER_UPDATE` |
| POST | `/users/{user_id}/deactivate` | `USER_REMOVE` |

Super admin bỏ qua các mã quyền nhưng vẫn phải đang hoạt động, đã đổi mật khẩu lần đầu và không được tự sửa tài khoản qua API quản trị. User thường không được quản trị super admin, cấp quyền vượt các quyền mình có, hoặc sửa user đang có quyền vượt quyền mình. Chỉ super admin được cấp cờ `is_super_admin`.

### Tạo user — 201

```json
{
  "email": "new.user@example.com",
  "password": "ReplaceWithTemporaryPassword123!",
  "permission_ids": [1, 2],
  "is_super_admin": false
}
```

`permission_ids` lấy từ `GET /permissions`; tối đa 500 ID. Bỏ qua hoặc gửi `[]` để tạo user chưa có quyền. Password tối thiểu 8 ký tự, còn phải đáp ứng chính sách Supabase. API tạo Auth user, xác nhận email theo luồng admin provisioning (không gửi email mời), lưu profile/quyền, rồi mở khóa Auth. `is_first_login=true`; user phải đổi mật khẩu trước khi dùng API quản trị. Không trả password; admin chuyển mật khẩu tạm qua kênh riêng.

### Cập nhật — 200

```json
{
  "email": "updated.user@example.com",
  "permission_ids": [2, 3],
  "is_super_admin": false
}
```

Chỉ gửi các trường muốn sửa. `permission_ids` thay thế toàn bộ quyền hiện tại; `[]` xóa hết quyền; bỏ trường này thì giữ nguyên. Không chấp nhận body rỗng, null hoặc trường lạ. Email được cập nhật cả Supabase Auth và profiles. Chưa có các cột họ tên/số điện thoại nên chưa nhận những trường đó. Đổi mật khẩu dùng API riêng.

### Ngừng hoạt động — 200

`POST /users/{user_id}/deactivate` không cần body. Giữ dữ liệu và quyền, đặt `profiles."isActive"=false`, rồi ban tài khoản Supabase Auth. Gọi lại cùng thao tác để đồng bộ trạng thái khi Auth gặp lỗi.

Mở hoạt động lại: `PATCH /users/{user_id}` với `{"is_active":true}`. PATCH `is_active=false` cần cả `USER_UPDATE` và `USER_REMOVE`. Trạng thái false, null hoặc thiếu sẽ bị backend chặn, kể cả khi access token chưa hết hạn. Login, refresh, đổi mật khẩu và các API bảo vệ đều kiểm tra trạng thái này. JWT đã cấp không tự biến mất; các dịch vụ khác truy cập Supabase trực tiếp cần tự áp dụng chính sách tương ứng.

### Response chung

```json
{
  "success": true,
  "data": {
    "id": "33333333-3333-4333-8333-333333333333",
    "email": "new.user@example.com",
    "is_super_admin": false,
    "is_first_login": true,
    "is_active": true,
    "created_at": "2026-09-09T00:00:00Z",
    "updated_at": "2026-09-09T00:00:00Z",
    "permissions": ["USER_VIEW"]
  }
}
```

`permissions` là các mã được gán thực tế trong `user_permissions`, không đọc/ghi `profiles.permissions`. FE map mã này với `permission_code` từ danh sách quyền. Login/refresh và danh sách user cũng bổ sung `is_active`. Các response ghi dùng `Cache-Control: no-store`.

## Lỗi và đồng bộ

401: thiếu/token sai; 403: thiếu quyền, inactive, tự sửa hoặc chưa đổi password; 404: user không tồn tại; 409: email trùng; 422: dữ liệu sai; 429: Auth giới hạn; 503: chưa cài SQL hoặc upstream lỗi. Response theo chuẩn `{"error":{"code":"...","message":"..."}}`.

Supabase Auth và public tables không có transaction chung. Không tự xóa tài khoản hoặc rollback mật khẩu/email sau timeout vì kết quả có thể đã ghi:

- `USER_PROVISIONING_INCOMPLETE`: Auth account đã tạo nhưng profile/quyền chưa xác nhận. Tài khoản mới vẫn bị ban. Admin kiểm tra Auth Users và profiles, đối chiếu theo email/UUID; không tự retry POST tạo user. Nếu thiếu profile, cần hoàn tất provisioning có kiểm soát hoặc xử lý tài khoản dang dở trong dashboard.
- `USER_EMAIL_SYNC_INCOMPLETE`: email Auth đã đổi, phần profile chưa xác nhận. Kiểm tra hai nơi rồi PATCH lại email/quyền mong muốn.
- `USER_AUTH_SYNC_INCOMPLETE`: profile đã lưu nhưng trạng thái Auth chưa xác nhận. Reload user rồi retry deactivate hoặc PATCH `is_active=true` tương ứng. Khi deactivate, backend đã chặn qua profile trước khi ban Auth.
- `AUTH_WRITE_UNCONFIRMED` / `USER_WRITE_UNCONFIRMED`: kiểm tra dữ liệu thực tế trước khi retry, không hiểu là chắc chắn chưa ghi.

Function khóa các thao tác ghi của API với nhau; thao tác ngoài function (dashboard, trigger, dịch vụ khác) không nằm trong phạm vi khóa này. Lỗi giữa Auth và DB được trả rõ ràng, không đảm bảo atomic xuyên hai hệ thống.

## Kiểm thử

`python -m pytest` chạy các test độc lập credentials, gồm quyền route, validation, trạng thái inactive, thứ tự provisioning và lỗi ghi một phần. SQL được kiểm tra trên PostgreSQL nhúng PGlite, không dùng database production:

```powershell
npm install --prefix ../../work/sql-test @electric-sql/pglite@0.5.8
$env:PGLITE_MODULE = (Resolve-Path ../../work/sql-test/node_modules/@electric-sql/pglite/dist/index.js).Path
node tests/sql_checks.mjs
```

`tests/user_management.sql` là schema giả chỉ dành cho database test trống, **không chạy trên Supabase**. Chỉ chạy file trong `migrations/` trên project thật. Test không xác nhận các custom trigger/RLS hiện có trong project; cần smoke test bằng tài khoản thử sau khi cài migration.
