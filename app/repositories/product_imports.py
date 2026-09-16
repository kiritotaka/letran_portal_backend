from postgrest.exceptions import APIError
from app.core.errors import ApiError


class ProductImportRepository:
    def __init__(self, client):
        self.client = client

    def call(self, function, **params):
        try:
            return self.client.rpc(function, params).execute().data
        except APIError as exc:
            codes = {'FORBIDDEN': 403, 'IMPORT_NOT_FOUND': 404, 'FILE_NOT_FOUND': 404,
                     'FILE_NOT_READY': 409, 'IDEMPOTENCY_CONFLICT': 409,
                     'IMPORT_NOT_READY': 409, 'IMPORT_QUEUE_FULL': 429,
                     'INVALID_INPUT': 422, 'IMPORT_LEASE_LOST': 409}
            if exc.message in codes:
                raise ApiError(codes[exc.message], exc.message, exc.message.replace('_', ' ').capitalize() + '.') from None
            if exc.code in {'PGRST202', 'PGRST205', '42P01'}:
                raise ApiError(503, 'PRODUCT_IMPORTS_NOT_INSTALLED', 'Install migration 009_product_import_preview.sql first.') from None
            raise ApiError(503, 'PRODUCT_IMPORTS_UNAVAILABLE', 'Retry with the same Idempotency-Key.') from None
        except Exception:
            raise ApiError(503, 'PRODUCT_IMPORTS_UNAVAILABLE', 'Product import service is unavailable.') from None

    def action(self, actor, action, job_id, data=None):
        return self.call('portal_product_import_action', p_actor_id=str(actor.id),
                         p_action=action, p_job_id=str(job_id), p_data=data or {})

    def worker(self, action, job=None, data=None):
        return self.call('portal_product_import_worker', p_action=action,
                         p_job_id=job['id'] if job else None,
                         p_token=job['lease_token'] if job else None, p_data=data or {})
