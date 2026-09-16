from postgrest.exceptions import APIError
from app.core.errors import ApiError


class FileRepository:
    def __init__(self, client): self.client=client

    def action(self,actor,action,file_id,data=None):
        try:
            return self.client.rpc('portal_uploaded_file_action',{
                'p_actor_id':str(actor.id),'p_action':action,'p_file_id':str(file_id),
                'p_data':data or {}}).execute().data
        except APIError as exc:
            codes={'FORBIDDEN':403,'FILE_NOT_FOUND':404,'IDEMPOTENCY_CONFLICT':409,
                   'FILE_DELETED':409,'INVALID_INPUT':422}
            if exc.message in codes:
                raise ApiError(codes[exc.message],exc.message,exc.message.replace('_',' ').capitalize()+'.') from None
            if exc.code in {'PGRST202','PGRST205','42P01'}:
                raise ApiError(503,'FILES_NOT_INSTALLED','Install migration 008_shared_uploads.sql first.') from None
            raise ApiError(503,'FILE_OPERATION_UNCONFIRMED','Retry the same file operation with the same key.') from None
        except Exception:
            raise ApiError(503,'FILES_UNAVAILABLE','File service is unavailable.') from None
