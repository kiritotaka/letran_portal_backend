from app.core.errors import ApiError
from postgrest.exceptions import APIError


def run(query):
    try:
        return query.execute()
    except APIError as exc:
        codes={'FORBIDDEN':403,'REQUEST_NOT_FOUND':404,'IDEMPOTENCY_CONFLICT':409,
               'REQUEST_ARCHIVED':409,'UPLOADS_PENDING':409,'NO_SOURCE_FILES':409,
               'UNSUPPORTED_TASK':422,'ANALYSIS_INPUT_TOO_LARGE':413}
        if exc.message in codes:
            raise ApiError(codes[exc.message],exc.message,exc.message.replace('_',' ').capitalize()+'.') from None
        if exc.code in {'PGRST202','PGRST205','42P01'}:
            raise ApiError(503,'ANALYSIS_NOT_INSTALLED','Install migration 004_document_analysis.sql first.') from None
        raise ApiError(503,'ANALYSIS_UNAVAILABLE','Analysis service is unavailable. Retry with the same Idempotency-Key.') from None
    except Exception:
        raise ApiError(503,'ANALYSIS_UNAVAILABLE','Analysis service is unavailable. Retry with the same Idempotency-Key.') from None


class AnalysisRepository:
    def __init__(self,client): self.client=client

    def enqueue(self,actor,request_id,job_id,model):
        return run(self.client.rpc('portal_enqueue_analysis',{'p_actor_id':str(actor.id),
            'p_request_id':str(request_id),'p_job_id':str(job_id),'p_model':model})).data

    def get(self,job_id):
        rows=run(self.client.table('portal_document_jobs').select('*').eq('id',str(job_id)).limit(1)).data
        if not rows: raise ApiError(404,'JOB_NOT_FOUND','Analysis job was not found.')
        return rows[0]

    def list(self,request_id,params):
        return run(self.client.table('portal_document_jobs').select('*',count='exact')
            .eq('request_id',str(request_id)).order('created_at',desc=True).order('id')
            .range(params.offset,params.offset+params.page_size-1))

    def claim(self): return run(self.client.rpc('portal_claim_analysis',{})).data

    def finish(self,job,result=None,error=None):
        return run(self.client.rpc('portal_finish_analysis',{'p_job_id':job['id'],
            'p_lease_token':job['lease_token'],'p_result':result,'p_error':error})).data

    def stage(self,job,value):
        return run(self.client.table('portal_document_jobs').update({'stage':value})
            .eq('id',job['id']).eq('status','processing').eq('lease_token',job['lease_token']))
