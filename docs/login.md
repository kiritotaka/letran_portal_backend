# Login API — tích hợp FE

`POST /api/v1/auth/login`, Content-Type: application/json.

```json
{"email":"user@example.com","password":"your-password"}
```

Response 200:

```json
{
  "success": true,
  "data": {
    "access_token": "<Supabase access token>",
    "refresh_token": "<Supabase refresh token>",
    "token_type": "bearer",
    "expires_in": 3600,
    "expires_at": 2000000000,
    "user": {
      "id": "11111111-1111-4111-8111-111111111111",
      "email": "user@example.com",
      "is_super_admin": false,
      "is_first_login": false,
      "permissions": ["users.read"]
    }
  }
}
```

Thời hạn/token/mã quyền trên chỉ minh họa; response thật do Supabase và database quyết định.

## FE

```typescript
const response = await fetch(`${API_BASE_URL}/auth/login`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email, password }),
});
const body = await response.json();
if (!response.ok) throw new Error(body.error?.message ?? "Đăng nhập thất bại");
const { access_token, refresh_token, user } = body.data;
// Dùng access_token cho Authorization: Bearer ... ở API được bảo vệ sau này.
// Không log token/mật khẩu. Ưu tiên giữ token trong memory.
```

`API_BASE_URL` local: `http://127.0.0.1:8000/api/v1`; production: URL Render thực tế + `/api/v1`.
Axios trả response thì đọc `response.data.data`; nếu interceptor đã trả body thì đọc `body.data`.

FE hiện có xử lý `is_first_login=true` bằng chuyển trang đổi mật khẩu.
Backend lần này chỉ trả cờ đó, chưa triển khai đổi mật khẩu; luồng này chưa hoàn tất.
Chưa có /auth/me, refresh, logout, hoặc các API danh sách được bảo vệ.
Khi access token hết hạn, hiện cần đăng nhập lại. Quyền trong response phục vụ UI,
không thay thế kiểm tra quyền server khi bổ sung API nghiệp vụ.

## Lỗi

Envelope giữ thống nhất với health: `{"error":{"code":"...","message":"..."}}`.

| HTTP | Code | Xử lý |
| --- | --- | --- |
| 401 | INVALID_CREDENTIALS | Sai thông tin hoặc tài khoản không khả dụng; dùng thông báo chung |
| 403 | PROFILE_NOT_FOUND | Auth hợp lệ nhưng thiếu profile portal; liên hệ admin |
| 422 | VALIDATION_ERROR | Email/password/body sai định dạng, hoặc field dư |
| 429 | AUTH_RATE_LIMITED | Supabase giới hạn login; thử lại sau |
| 503 | AUTH_UNAVAILABLE / PROFILE_UNAVAILABLE / SUPABASE_NOT_CONFIGURED / SUPABASE_UNAVAILABLE | Dịch vụ/config không khả dụng |

Không trả token nếu profile/quyền không đọc được. Không tự tạo profile, không sửa schema.
Password không trim hoặc áp chính sách tạo mật khẩu mới lên mật khẩu hiện có.
Super admin lấy từ profile database, nhận `["*"]`; user thường đọc user_permissions → permissions.
Không đọc profiles.permissions hoặc quyền do FE/user metadata gửi.

## Render và kiểm thử

1. Deploy commit mới trên Render (Blueprint hiện có hoặc Web Service đã kết nối repo).
2. Build: `pip install -r requirements.txt`.
3. Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
4. Điền SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY và CORS_ORIGINS trong Environment.
   CORS_ORIGINS phải là origin FE thực tế, không path/trailing slash.
5. Mở `/docs`, gọi login bằng tài khoản Supabase Auth có profile cùng id.
6. Kiểm tra email/password sai trả 401; user thường nhận đúng quyền; admin nhận ["*"].

Không bật hoặc thay đổi tài khoản test tự động. Test tự động dùng SDK thật với HTTP mock,
không gửi mật khẩu test lên database thật. Login thành công thực tế cần bạn thử bằng tài khoản của mình.

SDK sign-in dùng client riêng mỗi request, tách client service role đọc profile/quyền.
Supabase Auth chịu trách nhiệm kiểm tra mật khẩu và giới hạn login; backend chuyển tiếp 429.
Chưa bổ sung bộ giới hạn request phân tán riêng.

Tham khảo: https://supabase.com/docs/reference/python/auth-signinwithpassword
