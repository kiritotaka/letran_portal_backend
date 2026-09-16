# Danh mục sản phẩm — bước 1

Chạy `migrations/007_portal_products.sql` một lần sau 006 trên Supabase SQL Editor.
Chỉ tạo bảng portal_products và trigger cập nhật updated_at. Chưa import Excel, chưa có API.
Không xóa/tạo lại bảng khi đổi nguồn Excel. Nếu tên bảng đã tồn tại, migration dừng để kiểm tra.

| Cột | Ý nghĩa |
|---|---|
| id | UUID ổn định để liên kết từ form |
| product_code | Mã TP/BTP, duy nhất, không có khoảng trắng đầu/cuối |
| product_name | Tên TP/BTP |
| is_active | Mặc định true; ngừng sử dụng bằng false |
| created_at / updated_at | Thời điểm tạo/cập nhật |
| created_by / updated_by | User thực hiện, liên kết profiles |

Mã được so sánh phân biệt hoa/thường; importer sẽ trim khoảng trắng, không tự đổi hệ mã.
Backend phải truyền actor vào created_by/updated_by; updated_at tự cập nhật bằng trigger.
RLS bật, anon/authenticated không truy cập trực tiếp. service_role chỉ có select/insert/update,
không cấp DELETE. API sau này kiểm tra PRODUCT_* trước khi truy cập.

Kiểm tra file Du_Lieu_VatTu_Kho_ERP.xlsx ngày 16/09/2026: 50.747 dòng chi tiết,
865 mã TP/BTP sau trim, không có cùng mã khác tên, không thiếu mã/tên trong các dòng sản phẩm.
Dòng tổng cuối không phải sản phẩm. Đây là kiểm tra file mẫu, không đảm bảo các file sau giống vậy.
Danh mục bao gồm TP/BTP; không tự nhận định tất cả là thành phẩm.
Sản phẩm vắng trong báo cáo kho lần sau không bị tự động ngừng sử dụng.

Bước tiếp theo: module upload riêng và luồng import sản phẩm. Chưa thay đổi API tài liệu cũ.
