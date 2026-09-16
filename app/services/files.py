import hashlib
from app.core.errors import ApiError
from app.repositories.files import FileRepository
from app.services.file_policies import policy_for
from app.services.file_validation import validate_file
from app.services.storage import PrivateStorage


def upload_file(client,actor,file_id,purpose,upload):
    policy=policy_for(purpose,actor)
    content=upload.file.read(policy.max_bytes+1)
    name,mime=validate_file(upload.filename,content,policy)
    repo=FileRepository(client)
    row=repo.action(actor,'reserve',file_id,{'purpose':purpose,'original_name':name,
        'content_type':mime,'size_bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()})
    if row['status']=='ready': return row
    PrivateStorage(client).upload(row['bucket'],row['object_path'],content,mime)
    return repo.action(actor,'complete',file_id)


def download_url(client,actor,file_id):
    row=FileRepository(client).action(actor,'get',file_id)
    if row['status']!='ready': raise ApiError(409,'FILE_NOT_READY','File is not available for download.')
    url=PrivateStorage(client).download_url(row['bucket'],row['object_path'],row['original_name'])
    return {'file_id':str(file_id),'download_url':url,'expires_in':300}
