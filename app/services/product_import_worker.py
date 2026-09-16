import hashlib
import logging
import time
from threading import Event, Thread

import httpx
from supabase import ClientOptions, create_client

from app.core.errors import ApiError
from app.repositories.product_imports import ProductImportRepository
from app.services.product_import_parser import ImportFailure, parse_products

logger = logging.getLogger(__name__)


def process_import(client, job, stop):
    repo = ProductImportRepository(client)
    last_heartbeat = time.monotonic()
    started = last_heartbeat

    def checkpoint():
        nonlocal last_heartbeat
        if stop.is_set():
            raise InterruptedError()
        now = time.monotonic()
        if now - started > 120:
            raise ImportFailure('IMPORT_PROCESSING_TIMEOUT')
        if now - last_heartbeat >= 20:
            if not repo.worker('heartbeat', job):
                raise ImportFailure('IMPORT_ACCESS_REVOKED')
            last_heartbeat = now

    try:
        checkpoint()
        source = job['source']
        content = client.storage.from_(source['bucket']).download(source['object_path'])
        if len(content) != source['size_bytes'] or hashlib.sha256(content).hexdigest() != source['sha256']:
            raise ImportFailure('IMPORT_SOURCE_CHANGED')
        result = parse_products(source['original_name'], content, job['sheet_name'], checkpoint)
        checkpoint()
        repo.worker('finish', job, result)
    except InterruptedError:
        pass  # Durable lease expiry allows another worker to retry.
    except ApiError as exc:
        # Transport failures leave the lease for recovery; never expose SDK details.
        if exc.status < 500 and exc.code != 'IMPORT_LEASE_LOST':
            repo.worker('fail', job, {'error_code': exc.code})
    except ImportFailure as exc:
        repo.worker('fail', job, {'error_code': exc.code})
    except (ValueError, KeyError, OSError):
        repo.worker('fail', job, {'error_code': 'IMPORT_INVALID_FILE'})


def worker_loop(settings, stop):
    last_error = None
    while not stop.is_set():
        try:
            with httpx.Client(timeout=httpx.Timeout(45, connect=5)) as http:
                client = create_client(str(settings.supabase_url).rstrip('/'),
                    settings.supabase_service_role_key.get_secret_value(),
                    options=ClientOptions(httpx_client=http, auto_refresh_token=False, persist_session=False))
                job = ProductImportRepository(client).worker('claim')
                if job:
                    process_import(client, job, stop)
            last_error = None
        except Exception:
            if last_error is None:
                logger.warning('Product import worker unavailable; durable jobs will retry.')
            last_error = True
        stop.wait(5)


def start_worker(settings):
    stop = Event()
    Thread(target=worker_loop, args=(settings, stop), name='portal-product-import-worker', daemon=True).start()
    return stop
