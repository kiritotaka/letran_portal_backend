import logging
import time
from threading import Event, Thread
import httpx
from supabase import create_client, ClientOptions
from app.repositories.analysis import AnalysisRepository
from app.services.document_analysis import AnalysisFailure, source_parts, extract

logger=logging.getLogger(__name__)


def verify_access(client,job):
    profile=client.table('profiles').select('isActive,is_first_login,is_super_admin').eq('id',job['created_by']).limit(1).execute().data
    if not profile or profile[0]['isActive'] is not True or profile[0]['is_first_login'] is not False:
        raise AnalysisFailure('ACTOR_UNAVAILABLE')
    if profile[0]['is_super_admin'] is not True:
        from app.repositories.users import UserRepository
        if 'DOC_UPDATE' not in UserRepository(client).get_permissions(job['created_by']): raise AnalysisFailure('ACTOR_UNAVAILABLE')
    req=client.table('portal_document_requests').select('status').eq('id',job['request_id']).limit(1).execute().data
    if not req or req[0]['status']!='draft': raise AnalysisFailure('REQUEST_ARCHIVED')
    ids=[s['file_id'] for s in job['source_snapshot']]
    rows=client.table('portal_files').select('id,status,sha256').in_('id',ids).execute().data
    valid={r['id']:r for r in rows}
    if any(s['file_id'] not in valid or valid[s['file_id']]['status']!='ready' or valid[s['file_id']]['sha256']!=s['sha256'] for s in job['source_snapshot']):
        raise AnalysisFailure('SOURCE_CHANGED')


def process_job(client,settings,job,stop):
    repo=AnalysisRepository(client); started=time.monotonic()
    try:
        verify_access(client,job)
        contents=[]
        for source in job['source_snapshot']:
            if stop.is_set(): raise AnalysisFailure('WORKER_INTERRUPTED')
            if time.monotonic()-started>600: raise AnalysisFailure('SOURCE_READ_TIMEOUT')
            contents.append(client.storage.from_(source['bucket']).download(source['object_path']))
        parts,text_sources=source_parts(job['source_snapshot'],contents)
        verify_access(client,job)
        if stop.is_set(): raise AnalysisFailure('WORKER_INTERRUPTED')
        repo.stage(job,'analyzing')
        result=extract(settings,job['model'],parts,job['source_snapshot'],text_sources)
        repo.stage(job,'validating')
        repo.finish(job,result=result)
    except AnalysisFailure as exc:
        repo.finish(job,error=exc.code)
    except Exception:
        repo.finish(job,error='ANALYSIS_FAILED')


def worker_loop(settings,stop):
    last_error=None
    while not stop.is_set():
        try:
            with httpx.Client(timeout=httpx.Timeout(20,connect=5)) as http:
                client=create_client(str(settings.supabase_url).rstrip('/'),settings.supabase_service_role_key.get_secret_value(),
                    options=ClientOptions(httpx_client=http,auto_refresh_token=False,persist_session=False))
                job=AnalysisRepository(client).claim()
                if job: process_job(client,settings,job,stop)
            last_error=None
        except Exception as exc:
            # Do not log tokens, provider errors, signed URLs or document contents.
            code=getattr(exc,'code',type(exc).__name__)
            if code!=last_error: logger.warning('Analysis worker unavailable (%s)',code)
            last_error=code
        stop.wait(5)


def start_worker(settings):
    stop=Event()
    thread=Thread(target=worker_loop,args=(settings,stop),name='portal-analysis-worker',daemon=True)
    thread.start()
    return stop


if __name__=='__main__':
    from app.core.config import Settings
    settings=Settings()
    if not settings.gemini_api_key.get_secret_value() or not settings.supabase_url:
        raise SystemExit('Configure GEMINI_API_KEY and Supabase before running the worker.')
    worker_loop(settings,Event())
