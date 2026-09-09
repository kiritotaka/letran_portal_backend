# Letran Portal Backend

## Cập nhật: Login API

Đã bổ sung `POST /api/v1/auth/login` qua Supabase Auth, với router/service/repository,
request/response schemas và CORS POST. Xem [hợp đồng API và hướng dẫn FE/Render](docs/login.md).
Các phần phase 1 bên dưới mô tả nền tảng ban đầu; phạm vi hiện tại đã thêm login.
Đã bổ sung `POST /api/v1/auth/change-password` và `POST /api/v1/auth/change-password-first-login`.
Xem [hợp đồng đổi mật khẩu và hướng dẫn FE](docs/change-password.md).
Chưa có API refresh/logout/me hoặc API danh sách/phân quyền nghiệp vụ.

File bổ sung: `app/api/v1/auth.py`, `app/schemas/auth.py`,
`app/services/auth.py`, `app/repositories/__init__.py`, `app/repositories/users.py`,
`tests/test_login.py`, `docs/login.md`.
Đổi mật khẩu bổ sung `app/services/passwords.py`, `tests/test_passwords.py`,
`docs/change-password.md`; tái sử dụng schemas/router/repository auth hiện có.

Backend Python 3.12 + FastAPI, phase 1. Repository dự kiến: `kiritotaka/letran_portal_backend`.

## Phạm vi

- Cấu trúc module, cấu hình môi trường, Supabase Python SDK, CORS và JSON error handling.
- `GET /api/v1/health`: liveness, không phụ thuộc Supabase.
- `GET /api/v1/health/supabase`: kiểm tra quyền truy cập Data API tới bảng `profiles` hiện có bằng HEAD với limit 1; không trả profile rows, không count toàn bảng.
- Không migration, không tạo/sửa table, column hoặc Auth users. Không triển khai auth, permission, Gemini chat hoặc mock API frontend.

## Chạy local

Chạy lệnh từ thư mục project, với Python 3.12 đã cài:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

macOS/Linux dùng `.venv/bin/python` thay cho `.\.venv\Scripts\python.exe` và `cp .env.example .env`.

Điền credentials vào `.env` trên máy cá nhân. Không đưa service role key vào frontend hoặc git.

| Biến | Ý nghĩa |
| --- | --- |
| `SUPABASE_URL` | URL project Supabase; để trống thì dependency chưa được cấu hình |
| `SUPABASE_SERVICE_ROLE_KEY` | Secret backend dùng cho Supabase; bắt buộc để probe thành công |
| `GEMINI_API_KEY` | Tùy chọn, chỉ dự phòng cấu hình; phase 1 không sử dụng |
| `CORS_ORIGINS` | Danh sách origin cách nhau bằng dấu phẩy, không path hoặc dấu `/` cuối; trống để tắt CORS |

Environment variables ưu tiên hơn `.env`; `.env` được đọc từ working directory. URL/origin sai định dạng làm startup thất bại. CORS mặc định cho localhost cổng 3000 và 5173; production cần khai báo origin frontend thực tế. Không dùng wildcard, chưa bật cookie credentials; chỉ cho GET, headers Authorization và Content-Type. CORS không thay thế authentication.

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/supabase
```

Health ứng dụng trả HTTP 200:

```json
{"status":"ok","service":"letran-portal-backend"}
```

Supabase thành công trả HTTP 200 với service `supabase`. Chưa cấu hình trả HTTP 503:

```json
{"error":{"code":"SUPABASE_NOT_CONFIGURED","message":"Supabase is not configured."}}
```

Lỗi kết nối/quyền/table không truy cập được trả 503 `SUPABASE_UNAVAILABLE`; không lộ nội dung lỗi upstream. Probe không khẳng định toàn bộ schema hoặc Supabase Auth hoạt động. Swagger: `/docs`; OpenAPI: `/openapi.json`.

## Kiến trúc

- `app/main.py`: application factory nhận Settings để dễ test; CORS bọc ngoài FastAPI để áp dụng cả response 500.
- `app/api/v1/`: APIRouter versioned và health routes. Sync routes/dependencies chạy trong threadpool vì Supabase SDK dùng synchronous HTTP.
- `app/core/config.py`: pydantic-settings, SecretStr che secret trong repr, cấu hình được tạo một lần cho mỗi application.
- `app/core/errors.py`: lỗi JSON nhất quán cho 404/405, validation 422, dependency 503 và unexpected 500; không trả stack trace/input/secret. Log chỉ loại exception.
- `app/services/supabase.py`: dependency tạo SDK client mỗi request cần Supabase; transport timeout 5 giây, được đóng sau request. Tắt auto-refresh/persist Auth session. Không gọi Auth API; chưa dùng shared client để tránh chia sẻ trạng thái Auth giữa request.
- `app/schemas/`: response models và hợp đồng OpenAPI.
- Chỉ thêm module khi có tính năng thật ở phase sau; chưa thêm ORM/repository layer vì hiện chỉ cần SDK và health probe.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pip check
```

Test độc lập credentials/database: health, missing configuration, Supabase success/failure/timeout, SDK thật qua mock transport, CORS, 404, 422, 500 và môi trường/secrets. Không gọi hoặc thay đổi Supabase thật.

Dependencies trực tiếp được pin trong requirements; dependencies bắc cầu do pip resolve. `requirements-dev.txt` bổ sung pytest; Render chỉ cài runtime requirements.

## Render

Push project lên repo backend rồi tạo Blueprint từ `render.yaml`. Nhập `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `CORS_ORIGINS` qua Render Environment/Blueprint prompts (`sync: false`). `GEMINI_API_KEY` chưa cần; có thể thêm vào Environment ở phase sau.

Blueprint dùng Python 3.12.14, build `pip install -r requirements.txt`, start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`; health path `/api/v1/health`. Health deployment chỉ kiểm tra process, nên kiểm tra thêm Supabase endpoint sau khi điền credentials. Chưa deploy tự động trong lần bàn giao này.

## Danh sách file

```text
.env.example
.gitignore
README.md
requirements.txt
requirements-dev.txt
pytest.ini
render.yaml
app/__init__.py
app/main.py
app/api/__init__.py
app/api/v1/__init__.py
app/api/v1/router.py
app/api/v1/health.py
app/core/__init__.py
app/core/config.py
app/core/errors.py
app/services/__init__.py
app/services/supabase.py
app/schemas/__init__.py
app/schemas/health.py
tests/conftest.py
tests/test_config.py
tests/test_health.py
```

## Tài liệu đối chiếu

- [FastAPI: Bigger Applications](https://fastapi.tiangolo.com/tutorial/bigger-applications/)
- [Supabase Python: Initializing](https://supabase.com/docs/reference/python/initializing)
- [Render Blueprint specification](https://render.com/docs/blueprint-spec)
