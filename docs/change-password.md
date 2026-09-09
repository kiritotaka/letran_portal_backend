# Đổi mật khẩu

## Endpoints

- `POST /api/v1/auth/change-password`: tự đổi mật khẩu cho tài khoản đã có profile.
- `POST /api/v1/auth/change-password-first-login`: cùng quy trình nhưng chỉ cho profile
  có `is_first_login=true` hoặc null (xử lý null như login hiện tại).
  Nếu đã false, trả 409 `FIRST_LOGIN_ALREADY_COMPLETED`.

Cả hai xác thực lại bằng email + mật khẩu hiện tại trên Supabase Auth, không yêu cầu
Bearer token. Điều này phục vụ FE đang xóa session khi chuyển sang màn hình đổi
mật khẩu lần đầu. Không phải API quên mật khẩu hoặc admin reset mật khẩu.
Chỉ user có credentials đúng mới đổi được; is_super_admin không bỏ qua bước xác thực.
Không nhận user_id, quyền hoặc cờ admin từ request.

## Request

```json
{
  "email": "user@example.com",
  "current_password": "Old-password1!",
  "new_password": "New-password2!"
}
```

Content-Type: application/json. Hỗ trợ alias `currentPassword`, `newPassword` cho
FE hiện tại; gửi một bộ tên trường duy nhất, field dư hoặc alias trùng trả 422.
Mật khẩu mới từ 8 đến 4096 ký tự, khác mật khẩu hiện tại, không chỉ gồm khoảng trắng.
Không trim mật khẩu. Supabase có thể áp chính sách mạnh hơn; backend giữ nguyên chính sách đó.

## Response 200

```json
{
  "success": true,
  "message": "Password changed. Sign in with your new password.",
  "data": {
    "password_changed": true,
    "is_first_login": false,
    "requires_login": true
  }
}
```

Không trả mật khẩu hoặc token. Sau thành công, xóa session FE cũ rồi gọi
`POST /api/v1/auth/login` bằng mật khẩu mới; dùng `data.access_token`,
`data.refresh_token`, `data.user` theo [login contract](login.md).

## Tích hợp FE hiện tại

`authApi.changePasswordFirstLogin` hiện gửi đúng endpoint và camelCase được hỗ trợ.
Response chuẩn dùng `data.is_first_login`, không đặt email/cờ này ở cấp ngoài.
Cần cập nhật kiểu response trong `src/services/api.ts` tương ứng.

`AuthContext.changePasswordFirstLogin` hiện đọc `token/user/role` của mock sau auto-login.
Thay đoạn tự đọc và saveSession bằng gọi lại hàm `login(email, newPassword)` đã
hỗ trợ response backend `data.access_token`:

```typescript
const result: any = await authApi.changePasswordFirstLogin(email, currentPassword, newPassword);
// Axios interceptor hiện trả body; nếu nhận AxiosResponse thì dùng result.data.
const body = typeof result.success === "boolean" ? result : result.data;
if (!body?.success || !body.data?.password_changed) {
  return { success: false, message: body?.error?.message ?? "Đổi mật khẩu thất bại" };
}
clearSession();
const signedIn = await login(email, newPassword);
if (!signedIn.success) {
  return { success: false, message: "Mật khẩu đã đổi. Hãy đăng nhập bằng mật khẩu mới." };
}
return signedIn;
```

Đây là hướng dẫn tích hợp; lần cập nhật này chưa sửa repo frontend.
Hiển thị `error.message` khi nhận response lỗi; không tự động retry POST đổi mật khẩu.
Đổi mật khẩu xong nhưng login lại bị lỗi thì vẫn giữ thông báo rằng mật khẩu đã đổi.

## Lỗi và khôi phục

Envelope: `{"error":{"code":"...","message":"..."}}`.

| HTTP | Code | Ý nghĩa |
| --- | --- | --- |
| 401 | INVALID_CREDENTIALS | Sai thông tin hoặc tài khoản không khả dụng; chưa đổi mật khẩu |
| 401 | INVALID_SESSION | Phiên xác thực không còn hợp lệ |
| 403 | PROFILE_NOT_FOUND | Không có profile; chưa đổi mật khẩu |
| 403 | REAUTHENTICATION_REQUIRED | Supabase yêu cầu xác thực bổ sung/MFA; không bỏ qua chính sách |
| 409 | FIRST_LOGIN_ALREADY_COMPLETED | Dùng endpoint đổi mật khẩu thông thường |
| 422 | VALIDATION_ERROR | Body sai, mật khẩu mới quá ngắn/trùng mật khẩu cũ |
| 422 | PASSWORD_POLICY_VIOLATION | Supabase từ chối mật khẩu mới |
| 429 | AUTH_RATE_LIMITED | Giới hạn của Supabase; thử lại sau |
| 503 | AUTH_UNAVAILABLE / PROFILE_UNAVAILABLE | Không xác thực/đọc profile được trước bước đổi mật khẩu |
| 503 | PASSWORD_CHANGE_STATUS_UNKNOWN | Kết quả ghi Supabase Auth không xác định; thử login bằng mật khẩu mới trước, không tự replay request |
| 503 | PASSWORD_CHANGED_PROFILE_SYNC_FAILED | Auth đã đổi mật khẩu, nhưng cập nhật profile chưa được xác nhận |

Với `PASSWORD_CHANGED_PROFILE_SYNC_FAILED`, dùng mật khẩu mới để login. Nếu cờ
vẫn true, liên hệ admin hoặc tự thực hiện lại đổi mật khẩu bằng mật khẩu hiện tại mới
và một mật khẩu mới khác khi dịch vụ hoạt động lại. Không tiếp tục dùng mật khẩu cũ.

Supabase Auth và public.profiles không có transaction chung. Backend chỉ cập nhật
is_first_login=false sau khi Auth xác nhận thành công; không rollback mật khẩu.
Profile chỉ ghi is_first_login, updated_at (UTC), updated_by (id đã xác thực).
Không sửa schema, quyền hoặc tự tạo tài khoản.

Phiên tạm do bước xác thực tạo ra được sign_out với scope local khi xử lý xong.
Nếu cleanup lỗi, chỉ log loại exception; không che kết quả đổi mật khẩu.
Không bảo đảm thu hồi ngay mọi access JWT đã phát hành. Phiên khác tuân theo
vòng đời Supabase; backend chưa triển khai logout toàn thiết bị.

## Kiểm thử trên Render

1. Đợi deploy commit mới Live, mở `https://<backend>/docs`.
2. Dùng tài khoản test của bạn gọi endpoint lần đầu nếu profile.is_first_login=true.
3. Kiểm tra 200, rồi login bằng mật khẩu mới: user.is_first_login phải false.
4. Login bằng mật khẩu cũ phải trả 401.
5. Gọi lại endpoint lần đầu với credentials hiện tại phải trả 409.
6. Dùng endpoint thường để kiểm tra lần đổi tiếp theo nếu cần.

Test tự động chạy SDK thật qua HTTP mock, xác minh thứ tự:
xác thực → đọc profile → cập nhật Auth bằng user token → cập nhật đúng profile bằng
service-role client → đóng phiên tạm. Không đổi mật khẩu tài khoản thật trong test.

Tham khảo: [Supabase update_user](https://supabase.com/docs/reference/python/auth-updateuser).
