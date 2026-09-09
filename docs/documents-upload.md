# Hồ sơ tài liệu và upload — đợt 1

Đợt này triển khai Storage private, danh mục, hồ sơ, nhóm tài liệu và upload/download. Chưa chạy AI, chưa chuẩn hóa hoặc upload mẫu Word thật, chưa xuất tài liệu. Không gửi hợp đồng của người dùng cho bên thứ ba.

## Cài đặt trên Supabase và Render

1. Trong Supabase SQL Editor, chạy **migrations/002_portal_documents.sql** một lần. Migration chạy trong transaction; nếu có lỗi thì rollback, không chạy tiếp từng đoạn. Không chạy file tests/*.sql trên Supabase.
2. Migration tạo 7 bảng `portal_*`, function `portal_documents_write`, bucket private `portal_documents` (10 MiB) và policy riêng. Không sửa bảng hiện có của team. Nếu đã có tên trùng, migration dừng để kiểm tra, không tự sửa bucket/table cũ. Không chạy lại migration đã thành công.
3. Deploy commit mới lên Render. Không cần biến môi trường mới; giữ SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY và CORS_ORIGINS. GEMINI_API_KEY chưa sử dụng.
4. Login admin đã đổi mật khẩu lần đầu, mở /docs → Authorize. Test theo các bước dưới đây bằng file thử. API dùng dữ liệu thật sau khi cài SQL; file sẽ chiếm dung lượng Storage.

Missing table/function trả 503 `DOCUMENTS_NOT_INSTALLED` trước khi ghi Storage. Không tạo database objects khi server khởi động.

## Mô hình dữ liệu

| Bảng | Vai trò |
|---|---|
| portal_document_tasks | Tác vụ đầu ra, seed ACCEPTANCE_REPORT — Lập biên bản nghiệm thu |
| portal_document_types | Loại đầu vào: ECONOMIC_CONTRACT, INVOICE, PAYMENT_PROOF |
| portal_document_templates | Phiên bản mẫu theo tác vụ; một phiên bản active/tác vụ |
| portal_document_requests | Hồ sơ, tác vụ, mẫu đã chọn nếu có, tiêu đề, draft/archived, audit |
| portal_documents | Nhóm file thuộc cùng một tài liệu logic, loại tài liệu, tiêu đề |
| portal_files | Metadata file, SHA-256, bucket/path, uploading/ready/deleted, audit |
| portal_document_request_files | Gắn file vào hồ sơ và nhóm, thứ tự trang |

Seed mẫu chỉ có tên/định dạng DOCX, `is_active=false`, chưa có file mẫu thật. Vì vậy `template_id=null` khi tạo hồ sơ ở đợt này; FE hiển thị “Mẫu xuất chưa sẵn sàng”. Đợt xuất tài liệu sẽ chuẩn hóa mẫu, kích hoạt phiên bản và chốt mẫu cho hồ sơ trước khi xử lý. Không thể xuất từ các API hiện tại.

Tài liệu và hồ sơ dùng chung theo quyền, không giới hạn chủ sở hữu. Một nhóm có thể là một hợp đồng DOCX hoặc nhiều ảnh trang hợp đồng; nhóm khác có thể là chứng từ thanh toán. Không có AI tự nhận diện loại ở đợt này.

## API và quyền

Tất cả đường dẫn có tiền tố `/api/v1`; Bearer token bắt buộc, inactive/first-login bị chặn. Admin bỏ qua mã quyền.

| Method | Path | Quyền |
|---|---|---|
| GET | /document-tasks | DOC_VIEW hoặc DOC_CREATE hoặc DOC_UPDATE |
| GET | /document-types | Như trên |
| GET | /document-tasks/{task_id}/templates | Như trên; gồm cả mẫu inactive để hiển thị trạng thái |
| POST | /document-requests | DOC_CREATE |
| GET | /document-requests | DOC_VIEW |
| GET | /document-requests/{request_id} | DOC_VIEW |
| PATCH | /document-requests/{request_id} | DOC_UPDATE |
| POST | /document-requests/{request_id}/documents | DOC_CREATE |
| GET | /document-requests/{request_id}/documents | DOC_VIEW |
| POST | /document-requests/{request_id}/documents/{document_id}/files | DOC_CREATE |
| GET | /document-requests/{request_id}/files | DOC_VIEW |
| PATCH | /document-requests/{request_id}/files/{file_id} | DOC_UPDATE |
| POST | /document-requests/{request_id}/files/{file_id}/delete | DOC_REMOVE |
| GET | /document-requests/{request_id}/files/{file_id}/download-url | DOC_VIEW |

Tất cả danh sách phân trang `page=1&page_size=20`, tối đa 100/page. Response `{success:true,data:{items:[],pagination:{...}}}` như API users. Chi tiết/ghi trả `{success:true,data:{...}}`; lỗi `{error:{code,message}}`. Không đưa bucket/path hoặc hash nội bộ vào API response. No-store cho cả response và URL tải.

## FE: luồng mẫu

1. GET /document-tasks và /document-types, lấy UUID tương ứng.
2. POST /document-requests:

```json
{"task_id":"<UUID tác vụ>","title":"Nghiệm thu ETEC"}
```

Trả 201, lưu `data.id` làm request_id. Tải lại trang lấy danh sách/chi tiết để tiếp tục, không tạo hồ sơ mới mỗi lần mở trang.

3. POST /document-requests/{request_id}/documents:

```json
{"document_type_id":"<UUID HĐ Kinh tế>","title":"Hợp đồng chính"}
```

Trả 201, lưu document_id. Các ảnh của cùng hợp đồng cùng document_id, ảnh hóa đơn tạo nhóm riêng.

4. Upload từng file với multipart/form-data, field `file`, field `sort_order` (1–10000). Header `Idempotency-Key` là UUID do FE tạo **một lần cho mỗi file**:

```javascript
// Giữ fileId cùng file trong hàng đợi, tái sử dụng chính ID khi retry.
const fileId = crypto.randomUUID();
const body = new FormData();
body.append("file", selectedFile);
body.append("sort_order", "1");
const response = await fetch(
  `${API_BASE}/document-requests/${requestId}/documents/${documentId}/files`,
  { method: "POST", headers: {
      Authorization: `Bearer ${accessToken}`,
      "Idempotency-Key": fileId
    }, body }
);
// Không tự đặt Content-Type: trình duyệt phải thêm multipart boundary.
```

Upload thành công hoặc retry file đã hoàn tất đều trả **200** cùng file_id. File ready không bị upload lại. Dùng cùng key nhưng đổi nội dung, tên, nhóm hoặc tài khoản trả 409 `IDEMPOTENCY_CONFLICT` (nhóm không thuộc hồ sơ trả 404). Dùng key mới để thêm file mới.

Hiển thị tiến độ upload bằng XMLHttpRequest.upload.onprogress hoặc Axios onUploadProgress, giới hạn 2–3 file đồng thời. 100% byte gửi từ trình duyệt chưa khẳng định backend đã lưu xong: chỉ đánh dấu hoàn tất khi nhận 200/status ready. fetch ví dụ trên không tự cung cấp tiến độ upload.

Tải lại trang: GET /files để biết file ready/uploading; trình duyệt có thể yêu cầu chọn lại file còn lỗi, rồi retry bằng file_id cũ. Không có resume từng byte; retry gửi lại toàn bộ file.

5. GET /document-requests/{request_id}/files?document_id={document_id}&page=1&page_size=20 trả các file uploading/ready và thứ tự. Đã xóa không nằm trong danh sách. Nếu thứ tự trùng, file_id là thứ tự phụ ổn định; FE nên gán số thứ tự khác nhau.
6. PATCH /document-requests/{request_id}/files/{file_id} với `{"sort_order":2}` để đổi thứ tự. Giai đoạn hiện tại mỗi lần đổi một file.
7. GET /document-requests/{request_id}/files/{file_id}/download-url trả `download_url`, `expires_in:300`. Dùng URL tải như một capability tạm thời; ai giữ URL có thể tải trong thời hạn. Không lưu URL vào database, không log URL/token. Tài khoản phải có DOC_VIEW mới lấy URL mới.

## Trạng thái và giới hạn

- JPG/JPEG, PNG, PDF, DOCX; 10 MiB/file (10,485,760 byte), body multipart tối đa 11 MiB. Server kiểm tra số byte thực tế, không chỉ Content-Length.
- Tối đa 30 file chưa xóa và 30 nhóm/hồ sơ. Các reservation đang uploading cũng tính vào hạn mức.
- Ảnh tối đa 25 triệu pixel; PDF không mã hóa, 1–200 trang; DOCX tối đa 2.000 ZIP entries, tổng giải nén 50 MiB, không VBA. Kiểm tra nội dung/định dạng cơ bản, không phải dịch vụ quét malware hoặc OCR/chấm chất lượng ảnh.
- Uploading chưa có link tải. Lỗi upload giữ reservation để retry. `UPLOAD_UNCONFIRMED` hoặc `UPLOAD_FINALIZATION_UNCONFIRMED`: retry cùng file/key; không tự xóa object khi kết quả ghi chưa xác định.
- PATCH hồ sơ với title hoặc status draft/archived. Archived chặn thêm nhóm/upload/sửa thứ tự/xóa file; DOC_UPDATE có thể mở lại draft. Người có DOC_VIEW vẫn xem/tải file ready của hồ sơ archived.
- Delete là **xóa mềm**: chuyển deleted, chặn cấp URL mới, giữ object và audit. File đã xóa không thể hồi sinh bằng retry upload. URL đã cấp trước đó còn hiệu lực tối đa 5 phút. Chưa có purge tự động; object bị xóa mềm vẫn tính dung lượng. Chính sách lưu giữ/purge sẽ được chốt trước khi triển khai xóa vật lý; không xóa Storage trong một thao tác có thể đang upload song song.
- Không hỗ trợ chỉnh loại/tiêu đề nhóm trong đợt này; tạo nhóm với loại đúng. Không hard delete hồ sơ và chưa có quản trị danh mục trên API.

## Bảo mật và giới hạn vận hành

Backend service role truy cập dữ liệu; các bảng mới bật RLS, không cấp quyền anon/authenticated. SQL RPC recheck trạng thái và quyền của actor trong transaction. Restrictive Storage policy chặn truy cập trực tiếp bucket portal_documents kể cả project có policy permissive rộng; bucket khác giữ nguyên predicate truy cập cũ. Cần test thêm các policy/trigger tùy biến thực tế sau migration.

DB và Storage không có transaction chung: reserve metadata → upload deterministic path → complete. Khi timeout, bản ghi uploading có thể đã có object; retry hoàn tất. Không dùng upsert để thay nội dung file khác: SQL kiểm tra hash/nội dung/owner/key trước upload. Function serialize việc reserve để giới hạn 30 file không bị vượt do request đồng thời.

Backend tiếp nhận file trong request, chưa có background worker. File ready tồn tại khi server restart; upload đang truyền bị ngắt cần retry. PostgREST giữ timeout 5 giây; transport upload có read/write timeout 60 giây, connect 5 giây. Các tác vụ AI chạy nền thuộc đợt sau.

## Kiểm thử

```powershell
python -m pytest
python -m pip check
$env:PGLITE_MODULE = (Resolve-Path ../../work/sql-test/node_modules/@electric-sql/pglite/dist/index.js).Path
node tests/documents_sql_checks.mjs
```

PGlite cài ở scratch theo docs/user-management.md. Tests dùng mock transport hoặc PostgreSQL nhúng, không upload hay sửa user/database thật. Smoke test sau cài SQL: tạo hồ sơ/nhóm bằng admin, upload ảnh thử, retry cùng key, lấy link qua user DOC_VIEW, xác nhận user thiếu quyền bị 403.

Nguồn đối chiếu SDK: [Supabase Python upload](https://supabase.com/docs/reference/python/storage-from-upload), [signed download URLs](https://supabase.com/docs/reference/python/storage-from-createsignedurl).
