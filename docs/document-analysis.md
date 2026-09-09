# Phân tích tài liệu — đợt 2

API phân tích các file ready của một hồ sơ ACCEPTANCE_REPORT, trả dữ liệu nháp gồm 24 trường của mẫu đã duyệt. Chưa có API xác nhận/chỉnh sửa dữ liệu hoặc xuất Word. Không sửa nội dung file nguồn/mẫu. Không tự xác nhận nghiệm thu, hoàn thành hoặc thanh toán.

## Thiết lập

1. Supabase SQL Editor: chạy `migrations/004_document_analysis.sql` sau 002/003. Tạo riêng bảng `portal_document_jobs` và 3 function; không thay đổi schema/dữ liệu của team. Chỉ service_role truy cập trực tiếp được. Không chạy file test SQL trên project thật.
2. Render: deploy code mới, cấu hình Environment:
   - `GEMINI_API_KEY`: key Google AI hợp lệ, đủ quota; không đưa vào FE/Git.
   - `GEMINI_MODEL=gemini-3.6-flash`: có thể thay bằng model hỗ trợ ảnh/PDF và structured output mà tài khoản có quyền dùng.
   - `ANALYSIS_WORKER_ENABLED=true`: bật worker trong web service; mặc định false để không tự xử lý trước khi setup xong.
3. Bấm Phân tích bằng user DOC_UPDATE hoặc super admin. Việc này gửi nội dung nguồn tới Google Gemini và dùng quota của key đã cấu hình.

Kiểm tra thực tế khi triển khai: model metadata đọc được; gemini-2.5-flash trả 404 không cho tài khoản mới, Google đề nghị gemini-3.6-flash. Thử đoạn dữ liệu giả với 3.6 trả 429 AI_RATE_LIMITED. Chưa có lần phân tích live thành công, chưa gửi hợp đồng thật trong các test triển khai. Cần kiểm tra quota/billing của Google AI trước khi test end-to-end trên hồ sơ thật.

## FE: ba API

Tất cả dùng Bearer token. Base `/api/v1`.

### Bắt đầu

`POST /document-requests/{request_id}/jobs` — quyền DOC_UPDATE, không cần body.

Header `Idempotency-Key: <UUID>`: FE tạo một mã cho một lần phân tích. Khi POST timeout, retry đúng mã cũ. Trả **202** với `{success:true,data:{id,request_id,status,stage,...}}`. Lưu data.id làm job_id.

Một hồ sơ chỉ có một job queued/processing. Bấm nhiều lần trong khi chạy trả job đang hoạt động, không gọi AI thêm. Cùng key sau khi hoàn tất trả đúng job cũ, không phân tích lại. Muốn phân tích lại sau khi sửa tài liệu hoặc sau lỗi, dùng key mới khi job cũ đã completed/failed.

Hồ sơ phải draft, thuộc tác vụ ACCEPTANCE_REPORT, có ít nhất một file ready và không có file uploading. Tổng file nguồn tối đa 12 MiB/job; giới hạn upload 10 MiB/file vẫn giữ nguyên. API chụp metadata/hash/file order tại thời điểm enqueue, không tự gộp các file upload thêm sau đó. Nhiều hợp đồng độc lập nên tạo hồ sơ riêng.

### Theo dõi và lấy kết quả

`GET /document-jobs/{job_id}` — DOC_VIEW.

FE poll mỗi 3–5 giây, dừng khi completed/failed. Các stage:

| status | stage | Hiển thị |
|---|---|---|
| queued | queued | Đang chờ xử lý |
| processing | reading_sources | Đang đọc tài liệu |
| processing | analyzing | AI đang trích xuất |
| processing | validating | Đang kiểm tra dữ liệu |
| completed | completed | Sẵn sàng kiểm tra dữ liệu |
| failed | failed | Hiển thị error_code và nút Thử lại |

Không có phần trăm giả định cho AI. Kết quả completed nằm trong `data.extracted_data`:

```json
{
  "fields": [
    {
      "name": "contract_number",
      "value": "TEST-001",
      "sources": [{"file_id":"11111111-1111-4111-8111-111111111111","location":"đoạn đầu hợp đồng","quote":"Hợp đồng số TEST-001"}],
      "conflict": false,
      "status": "extracted"
    }
  ],
  "missing_fields": ["acceptance_date"],
  "warnings": ["AI_DRAFT_REQUIRES_REVIEW"],
  "requires_review": true
}
```

Ví dụ rút gọn; thực tế trả đủ 24 trường. `status` của field: extracted, missing, needs_input, conflict. FE render như văn bản, không dùng HTML từ AI. Dữ liệu là bản nháp, chưa phải thông tin đã xác nhận. Completion không có nghĩa tài liệu đã được nghiệm thu.

### Lịch sử và reload

`GET /document-requests/{request_id}/jobs?page=1&page_size=20` — DOC_VIEW, phân trang giống danh sách hồ sơ. Mới nhất trước, ID làm thứ tự phụ. Khi reload trang, lấy lịch sử; tìm job đang chạy rồi tiếp tục poll, không POST lại. Mỗi job có source_snapshot công khai gồm file_id, tên file, nhóm/loại và thứ tự, không có bucket/path/hash/lease token. Một lần phân tích sau tạo job mới, không ghi đè kết quả cũ.

## Dữ liệu nguồn và bằng chứng

- DOCX: đọc body, bảng, header/footer từ XML, không gửi nguyên DOCX vào Gemini. File có ảnh nhúng trả DOCX_IMAGES_REQUIRE_PDF để tránh bỏ qua ảnh: user chuyển sang PDF hoặc upload ảnh riêng. Vị trí nguồn DOCX là đoạn/mục, không tự đặt số trang.
- PDF/JPG/PNG: gửi inline cho Gemini; không tạo public URL hay Google Files API object. Tối đa 300 trang PDF/ảnh tổng cộng; DOCX tối đa 200.000 ký tự/file, 300.000 ký tự/job.
- Hash nội dung tải về phải khớp snapshot. Kiểm tra lại tài khoản, DOC_UPDATE, trạng thái hồ sơ và file trước khi gọi AI. Nếu file bị xóa/thay đổi trước lúc kiểm tra thì job thất bại. Xóa sau khi đã gửi không thu hồi dữ liệu đã gửi cho Google; không purge lịch sử ở đợt này.
- Field có giá trị phải có nguồn thuộc snapshot. Với DOCX, quote phải xuất hiện nguyên văn trong văn bản đã đọc; không khớp thì bỏ bằng chứng. Trích dẫn ảnh/PDF chưa được kiểm chứng độc lập, cần user kiểm tra.
- Ngày/nơi nghiệm thu, kết quả nghiệm thu, ngày thực hiện thực tế, chất lượng, số bản và remaining_amount luôn để người dùng nhập/xác nhận. paid_amount chỉ nhận nguồn nhóm PAYMENT_PROOF, không lấy từ lịch thanh toán trong hợp đồng. Chưa tự cộng nhiều chứng từ hay tính công nợ.
- Phát hiện mâu thuẫn dựa vào AI và được đánh dấu nếu model báo; không đảm bảo AI nhận diện mọi mâu thuẫn. Prompt xem nội dung tài liệu là dữ liệu không đáng tin, không làm theo lệnh trong tài liệu; không cấp công cụ hoặc khả năng truy cập URL cho model.

## Worker và lỗi

Hàng đợi nằm trong Supabase, không dùng FastAPI BackgroundTasks để giữ trạng thái. Worker trong web process claim bằng khóa hàng/skip locked và lease token. Mỗi worker xử lý một job một lúc; nhiều instance không claim cùng job. Lease 15 phút, hoàn tất chỉ được ghi bởi token hiện hành chưa hết hạn.

Nếu Render Free ngủ hoặc đang deploy, worker không tiếp tục chạy khi process dừng. Job queued giữ lại và tiếp tục khi service thức. Job processing quá lease chuyển failed/WORKER_INTERRUPTED khi worker chạy lại. Không tự retry gọi Gemini sau timeout/crash, vì Google có thể đã xử lý và tính quota. User chủ động phân tích lại bằng key mới.

Lỗi thường gặp:

| Mã | Cách xử lý |
|---|---|
| AI_NOT_CONFIGURED | Thêm key và bật worker |
| ANALYSIS_NOT_INSTALLED | Chạy SQL 004 |
| UPLOADS_PENDING | Hoàn tất/retry hoặc xóa mềm file lỗi |
| ANALYSIS_INPUT_TOO_LARGE / SOURCE_TOO_COMPLEX | Giảm số/dung lượng/trang file trong hồ sơ |
| AI_RATE_LIMITED | Kiểm tra quota/billing; thử lại sau khi giới hạn được giải quyết |
| AI_CREDENTIALS_REJECTED / AI_MODEL_UNAVAILABLE | Kiểm tra key và model |
| AI_TIMEOUT / WORKER_INTERRUPTED | Lần gọi trước có thể đã dùng quota; chạy job mới khi muốn thử lại |
| SOURCE_CHANGED / ACTOR_UNAVAILABLE | Kiểm tra file, trạng thái tài khoản và quyền |
| AI_INVALID_RESPONSE / AI_INCOMPLETE_RESPONSE | Không có kết quả đáng tin; kiểm tra nguồn rồi thử lại |

Không có kết quả fallback giả khi Gemini lỗi. Logs không ghi tài liệu, key, signed URL hay lỗi upstream nguyên văn. API chi tiết/lịch sử dùng Cache-Control: no-store.

## Kiểm thử

`python -m pytest` bao gồm validation đầu ra, bằng chứng giả, quyền route, trạng thái cấu hình, HTTP Gemini qua mock transport và worker lưu kết quả/lỗi. `node tests/documents_sql_checks.mjs` kiểm tra migration và queue/lease trong PGlite, không sửa Supabase thật. Test real Gemini dùng đoạn giả và đang bị 429 như ghi ở trên.

Nguồn: [Gemini structured output](https://ai.google.dev/gemini-api/docs/generate-content/structured-output), [document processing](https://ai.google.dev/gemini-api/docs/document-processing), [model catalog](https://ai.google.dev/gemini-api/docs/models).
