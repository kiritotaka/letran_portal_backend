# Nhập sản phẩm — bước xem trước

Đã có: upload dùng chung → tạo job → đọc XLSX/CSV → so sánh với `portal_products` → xem trước.
**Chưa có API xác nhận nhập. Không có thay đổi dữ liệu sản phẩm trong bước này.**

## Cài đặt

1. Chạy `007_portal_products.sql`, `008_shared_uploads.sql` nếu chưa chạy.
2. Chạy `009_product_import_preview.sql` một lần trong Supabase SQL Editor.
3. Deploy backend với requirements mới. Thêm `PRODUCT_IMPORT_WORKER_ENABLED=true` vào Render Environment và deploy lại.
4. Local: thêm biến tương tự vào `.env`, khởi động lại server.

Không cần dịch vụ mới, không dùng Gemini. `openpyxl` và `defusedxml` là thư viện Python trong cùng ứng dụng.
Worker chạy trong FastAPI. Render Free ngủ thì job chờ; khi ứng dụng thức, worker tiếp tục lấy job.
Job đang xử lý khi tiến trình dừng được nhận lại sau khi lease 3 phút hết hạn, tối đa 3 lượt.
Quyền tạo/đọc preview: `PRODUCT_IMPORT` hoặc super admin. User chỉ đọc job của mình; super admin đọc tất cả.
`PRODUCT_VIEW` và `PRODUCT_IMPORT_APPLY` riêng lẻ chưa cấp quyền xem file/preview ở giai đoạn này.

## Luồng FE

Các URL dưới đây tính từ `/api/v1`. Mọi request gửi `Authorization: Bearer <access_token>`.

### 1. Upload

`POST /files`: multipart `purpose=product_import` + `file`, header `Idempotency-Key` UUID.
Lấy `data.id` làm `file_id` khi `status=ready`. Xem `shared-files.md`.

### 2. Tạo job

`POST /product-imports`, Content-Type `application/json`, header `Idempotency-Key` UUID **riêng cho job**:

```json
{"file_id":"<UUID đã upload>","sheet_name":"Sheet"}
```

`sheet_name` có thể bỏ nếu XLSX chỉ có một sheet. XLSX nhiều sheet bắt buộc chọn tên chính xác; CSV không gửi sheet_name.
Trả HTTP 202, `{"success":true,"data":{"id":"...","status":"queued", ...}}`.
Lưu job ID trong URL/trạng thái bền vững của FE để tải lại trang vẫn theo dõi được.
Gửi lại cùng key và body trả job cũ; key cũ với file/sheet khác trả 409.
Giới hạn mỗi người tối đa 3 job queued/processing (429 `IMPORT_QUEUE_FULL`).

### 3. Theo dõi

`GET /product-imports/{job_id}` mỗi 3–5 giây. Dừng polling khi:

- `preview_ready`: đã có kết quả so sánh. Đây **không phải đã nhập thành công**.
- `failed`: hiển thị `error_code`, cho sửa file/chọn sheet rồi tạo job mới với key mới.

Khi `queued` hoặc `processing`, dùng trạng thái đang xử lý, không tự dựng phần trăm tiến độ.
Nếu request polling lỗi mạng/503, chờ và thử lại; không tự tạo job mới.

`summary` khi sẵn sàng gồm:

```json
{
  "source_rows":50747,"duplicate_rows":49882,"ignored_rows":1,
  "unique_codes":865,"sheet_name":"Sheet",
  "create":865,"update":0,"unchanged":0,"error":0,"total":865,"has_errors":false
}
```

Số create/update/unchanged phụ thuộc dữ liệu DB tại lúc so sánh. Ví dụ trên giả định bảng rỗng.
`duplicate_rows` đếm những lần lặp lại cùng mã và tên. Các mã mâu thuẫn và dòng lỗi vẫn được đưa vào preview để sửa;
`total` là số dòng preview, không phải tổng dòng Excel. Một mã mâu thuẫn có thể xuất hiện nhiều dòng lỗi.

### 4. Hiển thị xem trước

`GET /product-imports/{job_id}/rows?page=1&page_size=20&action=create`

- Bỏ `action` để xem tất cả; nhận `create`, `update`, `unchanged`, `error`.
- `page_size`: 1–100. Response dùng `data.items`, `data.pagination` như API danh sách hiện có.
- Mỗi dòng: `row_number`, `source_row` (dòng Excel), `product_code`, `product_name`, `occurrences`, `action`, `error_code`, `existing`.
- `existing`: giá trị cũ gồm `id`, `product_name`, `is_active`, `updated_at`; null cho mã chưa tồn tại.
- FE hiển thị mã, tên cũ, tên từ file, tác vụ dự kiến, lỗi và số dòng nguồn. Render tên như text, không chèn HTML từ file.
- Chưa hiện nút áp dụng có thể bấm vì API apply chưa triển khai.

Preview là ảnh chụp tại `finished_at`. Khi xây dựng API apply, phải kiểm tra lại catalog/phiên bản,
quyền `PRODUCT_IMPORT_APPLY` và yêu cầu xem lại nếu dữ liệu đã đổi; không áp dụng mù preview cũ.

## Quy tắc đọc và so sánh

- Dùng hai header `Mã TP/BTP`, `Tên TP/BTP`, tìm trong 20 dòng đầu; XLSX đọc tối đa 100 cột.
- NFC và bỏ khoảng trắng đầu/cuối; mã phân biệt hoa/thường. Mã phải là text để giữ số 0 đầu; không suy đoán mã từ số/formula.
- Cùng mã/cùng tên: gộp. Cùng mã/khác tên: lỗi `CONFLICTING_PRODUCT_NAME`, không tự chọn tên.
- Thiếu mã/tên, quá độ dài, công thức hoặc lỗi ô trong hai cột: đưa vào danh sách lỗi.
- Hai cột mã và tên đều trống: bỏ qua (bao gồm dòng tổng ERP); không lấy số liệu kho làm sản phẩm.
- Mã chưa tồn tại: create. Khác tên: update. Cùng tên: unchanged.
- Sản phẩm inactive vẫn giữ trạng thái inactive; file mới không tự kích hoạt lại.
- Mã không có trong file vẫn giữ nguyên. Không có tác vụ xóa hoặc deactivate tự động.
- Không liên kết vật tư/BOM trong bước này, không xử lý các cột nghiệp vụ khác.
- Giới hạn: upload 10 MiB; 100.000 dòng/sheet; tối đa 10.000 dòng preview (sau gộp, bao gồm lỗi);
  thời gian xử lý tối đa 120 giây qua các checkpoint. File quá lớn báo lỗi thay vì nhập một phần.
- CSV UTF-8, dấu phẩy. XLSX không thực thi công thức; đọc chế độ read-only.

## Lỗi chính

`IMPORT_HEADERS_NOT_FOUND`, `IMPORT_SHEET_REQUIRED`, `IMPORT_SHEET_NOT_FOUND`, `IMPORT_EMPTY`,
`IMPORT_ROW_LIMIT`, `IMPORT_PREVIEW_LIMIT`, `IMPORT_SOURCE_CHANGED`, `IMPORT_PROCESSING_TIMEOUT`,
`IMPORT_ACCESS_REVOKED`, `IMPORT_RETRY_EXHAUSTED`. Chi tiết lỗi nhà cung cấp không đưa ra FE/log.

File thuộc job queued/processing/preview_ready không thể xóa: API files trả 409 `FILE_IN_USE`.
Đây là thay đổi bảo vệ bổ sung trên API upload mới, không ảnh hưởng API upload tài liệu cũ.
Chưa có API hủy/cleanup preview. File và preview được giữ để đối chiếu; không có lịch tự xóa.

## Kiểm tra

`python -m pytest tests/test_product_imports.py` kiểm tra parser, worker, phân quyền và contract HTTP.
`tests/product_imports_sql_checks.mjs` chạy PGlite riêng với `PGLITE_MODULE` trỏ module đã cài:
kiểm tra idempotency, ownership, lease, pagination, file guard, RLS và bảng sản phẩm không đổi.
File ERP thực tế đã chạy local: 50.747 dòng, 865 mã duy nhất, 49.882 dòng lặp cùng mã/tên, 1 dòng tổng bỏ qua, 0 lỗi.
Kiểm tra này chỉ đọc file local, không upload hoặc import dữ liệu thật vào Supabase.
