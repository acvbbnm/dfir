"""Version-addressed evidence operations. Computed hashes are not provider attestations."""
import hashlib
from pathlib import PurePosixPath

CHUNK = 1024 * 1024

def safe_key(case_id, key):
    prefix = f'cases/{case_id}/'
    if not key.startswith(prefix) or '\\' in key or any(p in ('', '.', '..') for p in key.split('/')):
        raise ValueError('Object key is outside the case or is unsafe')
    return str(PurePosixPath(key).relative_to(prefix))

def hash_stream(body, max_bytes=None):
    digest, count = hashlib.sha256(), 0
    try:
        while True:
            block = body.read(CHUNK)
            if not block:
                return digest.hexdigest(), count
            count += len(block)
            if max_bytes is not None and count > max_bytes:
                raise ValueError('Object exceeds this worker limit')
            digest.update(block)
    finally:
        body.close()

def copy_verified(s3, source_bucket, final_bucket, key, kms_key, case_id, max_bytes):
    relative = safe_key(case_id, key)
    head = s3.head_object(Bucket=source_bucket, Key=key)
    version = head.get('VersionId')
    if not isinstance(version, str) or version in ('', 'null'):
        raise ValueError('Evidence staging must have S3 versioning enabled')
    if head['ContentLength'] > max_bytes:
        raise ValueError('Object exceeds current verifier limit; preserve staging and record PARTIAL (large-object worker is not implemented)')
    obj = s3.get_object(Bucket=source_bucket, Key=key, VersionId=version)
    digest, size = hash_stream(obj['Body'], max_bytes)
    if size != head['ContentLength']:
        raise ValueError('Object length changed during verification')
    reported = head.get('Metadata', {}).get('sha256')
    if reported and reported != digest:
        raise ValueError('Producer-reported hash does not match received bytes')
    # Content/version-specific destination is stable across retries. Never overwrite another version.
    stamp = hashlib.sha256((source_bucket+'\0'+key+'\0'+version).encode()).hexdigest()[:24]
    final_key = f'cases/{case_id}/objects/{stamp}/{relative}'
    existing = None
    try:
        existing = s3.head_object(Bucket=final_bucket, Key=final_key)
    except Exception as exc:
        code = getattr(exc, 'response', {}).get('Error', {}).get('Code')
        if code not in ('404', 'NoSuchKey', 'NotFound'):
            raise
    if existing:
        final_version = existing.get('VersionId')
        check = s3.get_object(Bucket=final_bucket, Key=final_key, VersionId=final_version)
        copied_hash, copied_size = hash_stream(check['Body'], max_bytes)
        if (copied_hash, copied_size) != (digest, size):
            raise ValueError('Existing final object conflicts with verified source')
    else:
        copied = s3.copy_object(Bucket=final_bucket, Key=final_key,
            CopySource={'Bucket':source_bucket, 'Key':key, 'VersionId':version},
            ServerSideEncryption='aws:kms', SSEKMSKeyId=kms_key,
            MetadataDirective='REPLACE', Metadata={'sha256':digest},
            ContentType=head.get('ContentType','application/octet-stream'))
        final_version = copied.get('VersionId')
    if not final_version or final_version == 'null':
        raise ValueError('Final evidence requires versioning')
    return {'key':final_key, 'relative_path':safe_key(case_id, final_key),
        'size_bytes':size, 'sha256':digest, 'status':'verified',
        'source':{'bucket':source_bucket,'key':key,'version_id':version},
        'destination':{'bucket':final_bucket,'key':final_key,'version_id':final_version},
        'original_locator':{'bucket':head.get('Metadata',{}).get('original-bucket'),
            'key':head.get('Metadata',{}).get('original-key'),'version_id':head.get('Metadata',{}).get('original-version')},
        'producer_sha256':reported, 'hash_kind':'computed_received_bytes',
        'source_kind':head.get('Metadata',{}).get('source-kind','unclassified')}
