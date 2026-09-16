# API upload file dùng chung — bước 1

## Triển khai

Chạy `migrations/008_shared_uploads.sql` một lần sau 006/007, rồi deploy backend.
Tạo bảng portal_uploaded_files và bucket private portal_uploads riêng. Không thay đổi
portal_files, portal_documents hoặc API upload tài liệu cũ. Không thêm dịch vụ hay dependency.
Chưa có worker/import Excel ở bước này; upload không ghi dữ liệu sản phẩm.

## Phạm vi

Service phân tách policy, validation, Storage và metadata. Purpose đầu tiên được bật:
`product_import`, nhận XLSX hoặc CSV UTF-8, tối đa 10 MiB/file (multipart 11 MiB).
Không nhận XLS/XLSM. MIME lấy từ nội dung/định dạng kiểm tra, không tin header FE.
XLSX giới hạn 2000 ZIP entries/50 MiB giải nén, không macro hoặc embedded object;
kiểm tra XML cơ bản, không thực thi công thức và không thay thế công cụ quét malware.
CSV chỉ kiểm tra UTF-8/cấu trúc cơ bản; kiểm tra cột/mã–tên sản phẩm thuộc bước import sau.
Các purpose khác chưa bật. Khi thêm nghiệp vụ, đăng ký policy, quyền, validator và cập nhật
allowlist SQL/bucket bằng migration; không cho FE tự chọn bucket hoặc storage path.

## Quyền

Upload: PRODUCT_IMPORT hoặc super admin. Đọc/xóa/tải: chủ file còn PRODUCT_IMPORT
hoặc super admin. PRODUCT_VIEW hay PRODUCT_IMPORT_APPLY riêng lẻ chưa cấp quyền truy cập
file của người khác ở bước này. User inactive/first-login bị chặn ở API và RPC.
Sau này job import cần tích hợp quyền người duyệt và chặn xóa file đang được sử dụng.

## API

Base /api/v1. Bearer token bắt buộc, response no-store.

| Method | Path | Kết quả |
|---|---|---|
| POST | /files | Upload một file, trả metadata/file_id trong data.id |
| GET | /files/{file_id} | Metadata và trạng thái |
| GET | /files/{file_id}/download-url | URL tải có hạn 300 giây |
| DELETE | /files/{file_id} | Xóa mềm, không xóa vật lý |

POST /files dùng multipart/form-data:
- file: file XLSX/CSV
- purpose: product_import
- Header Idempotency-Key: UUID tạo một lần cho mỗi file; giữ nguyên khi retry.

```javascript
const body = new FormData();
body.append('purpose', 'product_import');
body.append('file', selectedFile);
const response = await fetch(`${API_BASE}/files`, {
  method: 'POST',
  headers: { Authorization: `Bearer ${accessToken}`, 'Idempotency-Key': fileKey },
  body
});
```

Không tự đặt Content-Type. POST trả 200, gồm success và data:
id, purpose, original_name, content_type, size_bytes, status, created_by, created_at, updated_at.
Không trả bucket/path/hash. FE lưu data.id; chờ status ready mới báo upload xong.
GET download-url trả data.file_id, data.download_url, data.expires_in.

## Retry và vòng đời

Reserve metadata -> ghi Storage -> complete. Cùng key, owner, purpose, tên và nội dung thì
retry không tạo trùng. File ready không upload lại. Đổi nội dung/tên/purpose dùng key mới;
reuse key sai trả IDEMPOTENCY_CONFLICT (409). Key không hồi sinh được file đã xóa.
Upload hoặc complete timeout: retry cùng file/key. RPC kiểm tra quyền lại trong transaction.
Nếu user khác đoán file_id, metadata không được trả về.

Xóa mềm giữ object để tránh lỗi đua với upload và phục vụ audit. Metadata có status deleted,
không cấp URL mới; URL đã cấp còn dùng được tối đa 5 phút. Hiện chưa có TTL/dọn file vật lý,
file bỏ dở/deleted vẫn chiếm dung lượng. Không mặc định tự xóa dữ liệu.
Chưa có API danh sách file, gắn file vào nghiệp vụ hoặc sửa file. Các bước này làm khi tích hợp import.

## Lỗi chính

FILES_NOT_INSTALLED (503): chưa chạy SQL008.
FORBIDDEN (403): thiếu quyền.
FILE_NOT_FOUND (404): không tồn tại hoặc không thuộc user.
UNSUPPORTED_FILE_PURPOSE (422), UNSUPPORTED_FILE_TYPE / INVALID_FILE_CONTENT (415).
FILE_TOO_LARGE / UPLOAD_BODY_TOO_LARGE (413).
UPLOAD_UNCONFIRMED / FILE_OPERATION_UNCONFIRMED (503): retry cùng key.
FILE_NOT_READY / FILE_DELETED (409): không thể tải hoặc hoàn tất file.

## Kiểm thử

Python tests bao gồm policy, MIME, giới hạn, response redaction, CORS DELETE và retry.
PGlite tests kiểm tra ownership, quyền, khóa file, xóa mềm, RLS và bucket khác không bị ảnh hưởng.
Hai workbook BOM.xlsx và Du_Lieu_VatTu_Kho_ERP.xlsx đã qua validator local, chưa upload Supabase.
