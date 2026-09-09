# Refresh token

`POST /api/v1/auth/refresh`, Content-Type: application/json.
Không yêu cầu access token hoặc mật khẩu; refresh token là credential của request.

```json
{"refresh_token":"<refresh_token nhận từ login hoặc lần refresh gần nhất>"}
```

200 trả cùng envelope/schema với [login](login.md):
`{ "success": true, "data": { "access_token": "...", "refresh_token": "...",
"token_type": "bearer", "expires_in": 3600, "expires_at": 2000000000, "user": {...} } }`.
Thời hạn minh họa; dùng giá trị response thật.

Backend gọi Supabase refresh_session với token được truyền rõ ràng, client riêng từng
request; không dùng phiên cached hoặc tự phát hành JWT. Profile/quyền được đọc lại bằng
client service-role độc lập. Admin nhận ["*"]; user thường nhận quyền hiện có.
Không sửa schema hoặc lưu refresh token vào database riêng.

## FE

1. Lưu cả access_token, refresh_token, expires_at và user từ login.
2. Gọi refresh khi gần hết hạn hoặc khi API được bảo vệ trả 401 do phiên hết hạn.
3. Thay thế đồng thời cả hai token và user bằng data mới.
4. Chỉ một request refresh được chạy tại một thời điểm; request khác đợi cùng Promise.
   Nếu chia sẻ session giữa nhiều tab, cần phối hợp giữa các tab.
5. Retry request gốc tối đa một lần. Không áp interceptor refresh cho chính login,
   refresh hoặc đổi mật khẩu; 401 của chúng có thể là sai credentials.
6. Không refresh khi API trả 403 thiếu quyền.

Ví dụ gọi độc lập, không dùng interceptor có thể tự gọi lại refresh:

```typescript
const response = await fetch(API_BASE_URL + "/auth/refresh", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ refresh_token: currentRefreshToken }),
});
const body = await response.json();
if (!response.ok) {
  // Xử lý theo bảng lỗi; không log token hoặc body chứa token.
  throw new Error(body.error?.message ?? "Không thể làm mới phiên");
}
const newSession = body.data;
// Cập nhật store một lần với cả access_token, refresh_token, expires_at và user.
```

FE repo chưa được sửa trong lần bàn giao này.

## Lỗi

Envelope: `{"error":{"code":"...","message":"..."}}`.

| HTTP | Code | FE xử lý |
| --- | --- | --- |
| 401 | INVALID_REFRESH_TOKEN | Token không hợp lệ/đã bị thu hồi/phiên hết hạn: xóa session, yêu cầu login |
| 403 | PROFILE_NOT_FOUND | Không có profile portal: không tiếp tục phiên, liên hệ admin |
| 422 | VALIDATION_ERROR | Thiếu/sai token hoặc field dư: sửa request |
| 429 | AUTH_RATE_LIMITED | Dừng gọi liên tục, chờ trước khi thử lại |
| 503 | REFRESH_UNAVAILABLE | Không xác định kết quả refresh: login lại, không tự replay token cũ |
| 503 | REFRESH_PROFILE_UNAVAILABLE | Token đã refresh nhưng không đọc được profile/quyền: login lại |
| 503 | SUPABASE_NOT_CONFIGURED / SUPABASE_UNAVAILABLE | Backend chưa cấu hình hoặc khởi tạo client lỗi |

Refresh có thể đã xoay token trước khi response lỗi hoặc mất kết nối. Không giả định
token cũ luôn dùng lại được. Chính sách rotation/reuse do Supabase quản lý.
Response có Cache-Control: no-store; backend không sign_out phiên vừa refresh.
Không log hoặc đưa token vào query string. Ưu tiên giữ token trong memory.

## Test Render

Đợi commit mới Live, mở /docs, login bằng tài khoản của bạn, copy refresh_token vào
request refresh. Kiểm tra 200 và bộ token mới, sau đó dùng refresh_token vừa nhận cho
lần tiếp theo. Không cần đợi access token hết hạn để thử.
Test tự động dùng SDK thật qua HTTP mock, không refresh phiên người dùng thật.

Tham khảo: [Supabase refresh_session](https://supabase.com/docs/reference/python/auth-refreshsession).
