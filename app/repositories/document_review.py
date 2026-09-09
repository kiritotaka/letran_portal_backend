from postgrest.exceptions import APIError
from app.core.errors import ApiError


def run(query):
    try:
        return query.execute()
    except APIError as exc:
        codes = {'FORBIDDEN':403, 'REQUEST_NOT_FOUND':404, 'REVIEW_NOT_FOUND':404,
                 'REQUEST_ARCHIVED':409, 'REVISION_CONFLICT':409, 'IDEMPOTENCY_CONFLICT':409,
                 'JOB_NOT_READY':409, 'TEMPLATE_NOT_ASSIGNED':409, 'REVIEW_NOT_CONFIRMED':409,
                 'INVALID_INPUT':422}
        if exc.message in codes:
            raise ApiError(codes[exc.message], exc.message, exc.message.replace('_', ' ').capitalize()+'.') from None
        if exc.code in {'PGRST202','PGRST205','42P01'}:
            raise ApiError(503,'REVIEW_NOT_INSTALLED','Install migration 005_document_review.sql first.') from None
        raise ApiError(503,'REVIEW_UNAVAILABLE','Review operation is unconfirmed; retry the same request.') from None
    except Exception:
        raise ApiError(503,'REVIEW_UNAVAILABLE','Review service is unavailable.') from None


class ReviewRepository:
    def __init__(self, client): self.client = client

    def save(self, actor, request_id, key, payload):
        return run(self.client.rpc('portal_save_document_review', {
            'p_actor_id':str(actor.id), 'p_request_id':str(request_id), 'p_id':str(key),
            'p_payload':payload.model_dump(mode='json')})).data

    def get(self, request_id, revision=None):
        query=self.client.table('portal_document_reviews').select('*').eq('request_id',str(request_id))
        if revision is not None: query=query.eq('revision',revision)
        rows=run(query.order('revision',desc=True).limit(1)).data
        if not rows: raise ApiError(404,'REVIEW_NOT_FOUND','No saved review exists.')
        return rows[0]

    def exported(self, review_id):
        rows=run(self.client.table('portal_document_exports').select('*').eq('review_id',str(review_id)).limit(1)).data
        return rows[0] if rows else None

    def finish_export(self, actor, review_id, path, digest):
        return run(self.client.rpc('portal_record_document_export',{
            'p_actor_id':str(actor.id),'p_review_id':str(review_id),'p_path':path,'p_sha256':digest})).data
