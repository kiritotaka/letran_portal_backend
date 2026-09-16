from app.core.errors import ApiError


class PrivateStorage:
    def __init__(self, client): self.client=client

    def upload(self,bucket,path,content,mime):
        try:
            self.client.storage.from_(bucket).upload(path,content,file_options={
                'content-type':mime,'upsert':'true','cache-control':'0'})
        except Exception:
            raise ApiError(503,'UPLOAD_UNCONFIRMED','Upload unconfirmed. Retry the same file with the same Idempotency-Key.') from None

    def download_url(self,bucket,path,filename):
        try:
            data=self.client.storage.from_(bucket).create_signed_url(path,300,{'download':filename})
            url=data['signedURL']
            if not isinstance(url,str) or not url.startswith('https://'): raise ValueError()
            return url
        except Exception:
            raise ApiError(503,'STORAGE_UNAVAILABLE','File download URL is unavailable.') from None
