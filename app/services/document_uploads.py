import hashlib
from io import BytesIO
from pathlib import PurePosixPath
from warnings import catch_warnings, simplefilter
from xml.etree import ElementTree
from zipfile import ZipFile

from PIL import Image
from pypdf import PdfReader

from app.core.errors import ApiError
from app.repositories.documents import DocumentRepository

MAX_FILE_BYTES = 10 * 1024 * 1024
MIMES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
         ".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def inspect_file(name, content):
    name = (name or "").replace("\\", "/").split("/")[-1]
    if not name or len(name) > 255 or any(ord(c) < 32 for c in name):
        raise ApiError(422, "INVALID_FILENAME", "Provide a valid filename up to 255 characters.")
    if not content:
        raise ApiError(422, "EMPTY_FILE", "File is empty.")
    if len(content) > MAX_FILE_BYTES:
        raise ApiError(413, "FILE_TOO_LARGE", "Maximum file size is 10 MiB.")
    ext = PurePosixPath(name).suffix.lower()
    if ext not in MIMES:
        raise ApiError(415, "UNSUPPORTED_FILE_TYPE", "Use JPG, PNG, PDF or DOCX.")
    try:
        if ext in {".jpg", ".jpeg", ".png"}:
            with catch_warnings():
                simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(content)) as img:
                    expected = "PNG" if ext == ".png" else "JPEG"
                    if img.format != expected or img.width * img.height > 25_000_000:
                        raise ValueError()
                    img.verify()
        elif ext == ".pdf":
            if not content.startswith(b"%PDF-"):
                raise ValueError()
            pdf = PdfReader(BytesIO(content), strict=True)
            if pdf.is_encrypted or not 1 <= len(pdf.pages) <= 200:
                raise ValueError()
        else:
            with ZipFile(BytesIO(content)) as z:
                entries = z.infolist()
                if len(entries) > 2000 or sum(i.file_size for i in entries) > 50 * 1024 * 1024:
                    raise ValueError()
                names = z.namelist()
                if len(names) != len(set(names)) or any("vbaproject" in n.lower() for n in names):
                    raise ValueError()
                doc = z.read("word/document.xml")
                types = z.read("[Content_Types].xml")
                if b"<!DOCTYPE" in doc.upper() or b"<!DOCTYPE" in types.upper():
                    raise ValueError()
                root = ElementTree.fromstring(doc)
                if root.tag != "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document":
                    raise ValueError()
                types_root = ElementTree.fromstring(types)
                if not any(e.attrib.get("PartName") == "/word/document.xml" and
                           e.attrib.get("ContentType") == "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
                           for e in types_root):
                    raise ValueError()
    except Exception:
        raise ApiError(415, "INVALID_FILE_CONTENT", "File is invalid, encrypted, oversized when decoded, or does not match its extension.") from None
    return name, MIMES[ext]


def upload_file(client, actor, request_id, document_id, file_id, sort_order, upload):
    content = upload.file.read(MAX_FILE_BYTES + 1)
    name, mime = inspect_file(upload.filename, content)
    repo = DocumentRepository(client)
    data = repo.write(actor, "reserve_file", request_id=str(request_id), document_id=str(document_id),
                      file_id=str(file_id), sort_order=sort_order, original_name=name,
                      content_type=mime, size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    if data["status"] == "ready":
        return data
    try:
        # Same UUID may only reserve the same content/metadata and owner. Safe to
        # retry an ambiguous Storage write without creating a second object.
        client.storage.from_(data["bucket"]).upload(data["object_path"], content,
            file_options={"content-type": mime, "upsert": "true", "cache-control": "0"})
    except Exception:
        raise ApiError(503, "UPLOAD_UNCONFIRMED", "Upload is unconfirmed. Retry the same file with the same Idempotency-Key.") from None
    try:
        return repo.write(actor, "complete_file", request_id=str(request_id), file_id=str(file_id))
    except ApiError as exc:
        if exc.status in {403, 404, 409}:
            raise
        raise ApiError(503, "UPLOAD_FINALIZATION_UNCONFIRMED", "Storage upload finished but metadata is unconfirmed. Retry with the same Idempotency-Key.") from None


def download_url(client, request_id, file_id):
    data = DocumentRepository(client).file_for_request(request_id, file_id)
    if data["status"] != "ready":
        raise ApiError(409, "FILE_NOT_READY", "File is not available for download.")
    try:
        result = client.storage.from_(data["bucket"]).create_signed_url(
            data["object_path"], 300, {"download": data["original_name"]})
        url = result["signedURL"]
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ValueError()
    except Exception:
        raise ApiError(503, "STORAGE_UNAVAILABLE", "Download URL is unavailable.") from None
    return {"file_id": str(file_id), "download_url": url, "expires_in": 300}
