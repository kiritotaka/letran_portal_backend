# Lưu dữ liệu đã kiểm tra và xuất Word

## Triển khai

Chạy migrations/005_document_review.sql trên Supabase sau 004, rồi deploy backend.
Chỉ thêm portal_document_reviews, portal_document_exports và hai RPC service_role.
Không sửa bảng của team, không sửa kết quả AI. Không cần biến môi trường/dependency mới.

## Luồng FE

1. Mở trang: GET /api/v1/document-requests/{request_id}/review.
   Nếu REVIEW_NOT_FOUND (404), lấy kết quả job completed làm dữ liệu khởi tạo.
   Nếu có bản đã lưu, dùng fields của bản đó, không ghi đè bằng kết quả AI mới.
2. Hiển thị form 24 trường. Cho phép user sửa cả trường AI đã điền.
3. Lưu nháp: PUT review, confirmed=false. Có thể còn giá trị null.
4. Xác nhận: user kiểm tra nội dung và các câu hoàn thành/thanh lý cố định trong mẫu,
   PUT review với confirmed=true. Lưu thành công mới cho xuất.
5. Xuất: POST exports với revision vừa được server trả về. Không gửi lại fields ở bước xuất.
6. Tải lại trang: GET review để khôi phục form; GET exports/{revision}/download-url nếu đã xuất.

Tất cả API dùng Authorization: Bearer <access_token>. Base URL /api/v1.
GET yêu cầu DOC_VIEW; PUT review và POST exports yêu cầu DOC_UPDATE; super admin được phép.

### PUT /document-requests/{request_id}/review

Header Idempotency-Key: UUID mới cho mỗi thao tác lưu. Khi timeout, retry cùng key và cùng body.
Body:

```json
{
  "analysis_job_id": "UUID job completed thuộc hồ sơ",
  "expected_revision": 0,
  "confirmed": false,
  "fields": [
    {"name": "contract_number", "value": "19.06/2026/HĐKT-ETEC-LT"}
  ]
}
```

Ví dụ rút gọn: thực tế phải gửi đủ 24 name, mỗi name xuất hiện đúng một lần, value có thể null.
Chỉ gửi name/value; không gửi sources, status, display_value hoặc basis.
expected_revision=0 cho lần đầu; những lần sau lấy revision từ GET/PUT gần nhất.
Response 200: success=true, data gồm id, request_id, analysis_job_id, revision, confirmed,
fields, template_id, created_by, created_at. Mỗi lần lưu là một bản bất biến mới.
409 REVISION_CONFLICT: có người đã lưu bản mới, GET lại để đối chiếu, không tự ghi đè.
409 IDEMPOTENCY_CONFLICT: key đã dùng với body hoặc user/hồ sơ khác.

Giá trị tiền là chuỗi số nguyên không có dấu phẩy, ví dụ "1101600000"; không nhận số âm hoặc phần lẻ.
Ngày dùng DD/MM/YYYY và phải là ngày hợp lệ. Số bản 1–100; số bản mỗi bên không vượt tổng.
Không tự lấy ngày/nơi nghiệm thu từ ngày/nơi ký hợp đồng. Hai trường điện thoại được phép null.
Khi confirmed=true, 22 trường còn lại phải có giá trị. Giá trị plain text một dòng, tối đa 6000 ký tự.
Ngày bắt đầu thực tế không được sau ngày kết thúc. Không tự tính tiền còn lại từ lịch thanh toán.

### GET /document-requests/{request_id}/review?revision=1

Bỏ revision để lấy bản mới nhất. 404 REVIEW_NOT_FOUND nếu chưa lưu hoặc không có phiên bản đó.
User có thể dùng endpoint này xem lại bản đã xuất trước đó.

### POST /document-requests/{request_id}/exports

```json
{"revision": 1}
```

Response 200:

```json
{"success":true,"data":{"review_id":"UUID","revision":1,
"filename":"acceptance-report-v1.docx","download_url":"https://...","expires_in":300}}
```

Chỉ xuất bản confirmed. Tạo Word đồng bộ, không gọi Gemini. Một bản lưu chỉ có một bản xuất được ghi nhận.
Retry cùng revision sẽ trả URL mới của bản xuất cũ; không ghi đè bản đã xuất bằng dữ liệu sửa sau đó.
Muốn xuất dữ liệu khác: PUT lưu bản mới, rồi POST với revision mới.
Mẫu sử dụng template_id và đường dẫn đã chụp lúc lưu, không chọn mẫu active mới nhất.
Các file mẫu đã dùng phải giữ bất biến trong Storage; không ghi đè nội dung tại cùng đường dẫn.

### GET /document-requests/{request_id}/exports/{revision}/download-url

Cấp URL tải mới (5 phút), không tạo file mới. 404 EXPORT_NOT_FOUND nếu chưa xuất phiên bản đó.
URL là signed URL của bucket private portal_documents, không lưu URL vào database.

## Định dạng và giới hạn

Word giữ XML định dạng, bảng và chữ ký của mẫu; chỉ thay placeholder {{name}}, kể cả khi Word chia
placeholder qua nhiều run. Không thực thi Jinja hoặc mã trong template. Placeholder lạ/lỗi trả TEMPLATE_INVALID.
Tiền xuất theo dạng 1,101,600,000. Điện thoại null xuất chuỗi rỗng; không tự thêm thông tin thiếu.
Giữ nguyên số biên bản và các câu hoàn thành/thanh lý đã cố định trong mẫu.
Chưa xuất PDF, chưa có API upload/quản lý mẫu mới, chưa có lịch sử phân trang riêng (GET theo revision).

Lưu trữ và ghi DB là hai bước: nếu upload xong nhưng DB lỗi, file chưa được ghi nhận có thể còn trong
Storage. Retry cùng revision; không xóa file tự động. Không gửi secret/path nội bộ trong response.
Xuất bản dài có thể làm tăng số trang; cần kiểm tra file Word trước khi sử dụng chính thức.

## Kiểm thử

Python tests: validation, quyền, khôi phục bản lưu, split-run placeholder, escape XML, tiền,
retry xuất không upload lại, lỗi URL và giữ dữ liệu riêng. PGlite: migration, quyền, retry,
xung đột revision, archive, RLS, ghi nhận export duy nhất. Không chạy SQL test trên Supabase thật.
