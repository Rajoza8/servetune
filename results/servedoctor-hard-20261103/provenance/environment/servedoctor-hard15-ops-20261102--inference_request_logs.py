#!/usr/bin/env python3
"""One explicitly authorized container-log request; never prints raw logs or URLs.

API credential is used internally for the fixed authenticated request only.
No SSH/lifecycle/model/ledger operation or request retry exists. The returned
S3 URL and raw log bytes stay in memory. Full redacted text is persisted, but
only fixed diagnostic projections/counts/hashes are returned to the caller.
No caller-supplied endpoint allowed; an existing receipt resumes without PUT.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import ssl
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

OPS = Path(__file__).resolve().parent
PROJECT = 'servedoctor-hard15-inference-20261103'
LIMIT = 1024 * 1024


class RedirectBlocked(RuntimeError): pass
class ResultShapeError(ValueError): pass
class LogTooLarge(ValueError): pass
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): raise RedirectBlocked()


def write_new(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2); stream.write('\n'); stream.flush()


def utc(): return datetime.now(timezone.utc).isoformat()
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def api_request(instance):
    # Normal provider authentication, isolated from all persisted/returned data.
    key = (Path.home()/'.config/vastai/vast_api_key').read_text().strip()
    if not key: raise ValueError('EmptyCredential')
    request = urllib.request.Request('https://console.vast.ai/api/v0/instances/request_logs/'+str(instance)+'/',
        data=json.dumps({'tail':'1000','daemon_logs':False}).encode(),
        headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='PUT')
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile='/etc/ssl/cert.pem')),NoRedirect())
    with opener.open(request,timeout=20) as response:
        raw = response.read(65537)
        if len(raw)>65536: raise ResultShapeError()
        value = json.loads(raw)
        if not isinstance(value,dict) or value.get('success') is False or not isinstance(value.get('result_url'),str):
            raise ResultShapeError()
        return {'http_status':response.status,'result_url':value['result_url']}


def download(url,timeout=20):
    address = urlsplit(url)
    if (not isinstance(url,str) or len(url)>8192 or address.scheme!='https'
            or address.username is not None or address.password is not None or address.fragment
            or address.port not in (None,443) or not address.hostname
            or not (address.hostname=='s3.amazonaws.com' or address.hostname.endswith('.amazonaws.com'))):
        raise ResultShapeError()
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile='/etc/ssl/cert.pem')),NoRedirect())
    # No provider Authorization header is forwarded to object storage.
    with opener.open(urllib.request.Request(url,method='GET'),timeout=timeout) as response:
        raw = response.read(LIMIT+1)
        if len(raw)>LIMIT: raise LogTooLarge()
        return response.status,raw


PATTERNS = (
    ('bad_ownership_or_modes',r'bad ownership or modes|bad owner or permissions|permissions.*too open'),
    ('authorized_keys_unreadable',r'(authorized_keys.*(?:permission denied|not found|no such file))|(?:could not|cannot|failed to) open.*authorized_keys'),
    ('missing_host_keys',r'no hostkeys available|could not load host key'),
    ('missing_sshd_directory',r'missing privilege separation directory'),
    ('sshd_config_error',r'(sshd_config.*(?:error|bad|invalid))|(?:bad configuration option)'),
    ('ssh_startup_failure',r'(?:sshd|ssh server).*(?:failed|failure|error|unable|not found)'),
    ('ssh_startup_marker',r'(?:starting|started|listening|running).*ssh|server listening on'),
    ('onstart_failure',r'onstart.*(?:failed|error|not found|no such|permission denied)'),
    ('onstart_marker',r'onstart|SERVETUNE_SSH_REPAIR_(?:BEGIN|END)'),
    ('entrypoint_failure',r'entrypoint.*(?:failed|error|not found|no such|permission denied)'),
    ('entrypoint_marker',r'entrypoint'),
    ('startup_marker',r'container.*(?:starting|started)|(?:starting|started).*container'),
)
PATHS = ('/root/.ssh/authorized_keys','/root/.ssh','/root','/etc/ssh/sshd_config','/run/sshd','/root/onstart.sh')
SENSITIVE = re.compile(r'api.?key|password|secret|token|authorization|bearer|ssh-(?:ed25519|rsa)|ecdsa-sha2|PRIVATE KEY',re.I)
ASSIGNMENT = re.compile(r'''(?ix)\b(?:[a-z0-9]+[_-])*(?:api[_-]?key|access[_-]?key|token|secret|password|passwd|passphrase|authorization|credentials?|private[_-]?key)(?:[_-][a-z0-9]+)*\b["']?\s*[:=]''')
URL = re.compile(r'''https?://[^\s<>"']+''',re.I)
TOKEN = re.compile(r'(?<![A-Za-z0-9_+/=-])[A-Za-z0-9_+/=-]{24,}(?![A-Za-z0-9_+/=-])')
KEY_BEGIN = re.compile(r'-----BEGIN [A-Z0-9 ]*(?:PRIVATE|PUBLIC|SECRET) KEY(?: BLOCK)?-----',re.I)
KEY_END = re.compile(r'-----END [A-Z0-9 ]*(?:PRIVATE|PUBLIC|SECRET) KEY(?: BLOCK)?-----',re.I)


def secret_like_token(value):
    entropy = -sum((value.count(c)/len(value))*math.log2(value.count(c)/len(value)) for c in set(value))
    return (bool(re.fullmatch(r'[0-9a-fA-F]{32,}',value))
            or (any(c.isalpha() for c in value) and any(c.isdigit() for c in value) and entropy>=3.2)
            or (len(value)>=32 and entropy>=4.1))


def sanitize(raw):
    """Full text is for opaque storage/human review, never model-facing output."""
    output=[];private=False
    stats={'sensitive_lines':0,'key_block_lines':0,'urls':0,'high_entropy_values':0}
    for line in raw.decode(errors='replace').splitlines():
        if KEY_BEGIN.search(line):private=True
        if private:
            stats['key_block_lines']+=1;output.append('[REDACTED key block]')
            if KEY_END.search(line):private=False
            continue
        if (ASSIGNMENT.search(line) or re.search(r'\bBearer\s+\S+',line,re.I)
                or re.search(r'\b(?:ssh-ed25519|ssh-rsa|ecdsa-sha2-\S+)\s+',line)):
            stats['sensitive_lines']+=1;output.append('[REDACTED sensitive line]');continue
        def url_replace(match):stats['urls']+=1;return '[REDACTED URL]'
        line=URL.sub(url_replace,line)
        def token_replace(match):
            if secret_like_token(match[0]):stats['high_entropy_values']+=1;return '[REDACTED value]'
            return match[0]
        output.append(TOKEN.sub(token_replace,line))
    stats['unterminated_key_block']=private
    return '\n'.join(output)+'\n',stats


def project(raw):
    findings=[];private=False;dropped=0;lines=raw.decode(errors='replace').splitlines()
    for number,line in enumerate(lines,1):
        if '-----BEGIN ' in line and 'PRIVATE KEY-----' in line:private=True
        if private:
            dropped+=1
            if '-----END ' in line and 'PRIVATE KEY-----' in line:private=False
            continue
        if SENSITIVE.search(line):dropped+=1;continue
        for category,pattern in PATTERNS:
            if re.search(pattern,line,re.I):
                findings.append({'line_number':number,'category':category,
                                 'known_paths':[path for path in PATHS if re.search(re.escape(path)+r'''/?(?=$|[\s"',:;])''',line)]})
    return {'raw_log_sha256':hashlib.sha256(raw).hexdigest(),'raw_bytes':len(raw),'raw_lines':len(lines),
            'sensitive_lines_discarded':dropped,'diagnostics':findings,
            'onstart_evidence_observed':any(row['category'].startswith('onstart') for row in findings),
            'startup_evidence_observed':any(any(term in row['category'] for term in ('startup','entrypoint')) for row in findings),
            'absence_interpretation':'No matching projected line is not proof startup/onstart did not run.',
            'projection':'Returned findings use fixed categories/known paths only; freeform log text is never emitted to progress.'}


def consume_existing(marker,instance,scope_sha,ops):
    if marker.is_symlink() or not marker.is_file():raise ValueError('Prior dispatch is not regular')
    previous=json.loads(marker.read_text());declared=Path(previous['evidence_directory'])
    if declared.is_symlink():raise ValueError('Prior evidence directory is linked')
    folder=declared.resolve()
    if (previous.get('instance_id')!=instance or previous.get('scope_sha256')!=scope_sha
            or previous.get('project')!=PROJECT or folder.parent!=ops or folder.is_symlink()):
        raise ValueError('Prior log dispatch binding differs')
    receipt=folder/'receipt.json'
    if not receipt.exists():
        return {'project':PROJECT,'instance_id':instance,'scope_sha256':scope_sha,'completed':False,
                'failure':{'class':'PriorRequestOutcomeUnknown','http_status':None},'put_replays':0,
                'resumed_without_put':True,'existing_dispatch':{'path':str(marker),'sha256':sha(marker)}}
    if receipt.is_symlink() or not receipt.is_file():raise ValueError('Prior receipt is not regular')
    value=json.loads(receipt.read_text())
    if (value.get('project')!=PROJECT or value.get('instance_id')!=instance or value.get('scope_sha256')!=scope_sha
            or value.get('payload')!={'tail':'1000','daemon_logs':False}):raise ValueError('Prior receipt binding differs')
    if value.get('completed') is True:
        path=folder/'container-sanitized.log'
        if path.is_symlink() or sha(path)!=value.get('sanitized_log_sha256'):raise ValueError('Sanitized log changed')
    # Never read/return the text log; the receipt contains structured findings only.
    value.update(resumed_without_put=True,existing_receipt={'path':str(receipt),'sha256':sha(receipt)})
    return value


def collect(instance,out,*,ops=OPS,request=api_request,fetch=download,sleep=time.sleep,clock=time.monotonic):
    ops=Path(ops).resolve();out=Path(out)
    if not out.is_absolute():out=ops.parent.parent/out
    if out.parent.resolve()!=ops or not re.fullmatch('[a-z0-9][a-z0-9-]{0,95}',out.name):
        raise ValueError('Fresh direct Hard OPS evidence directory required')
    scope_path=ops/'rental-scope.json';session_path=ops/'session.json'
    if any(path.is_symlink() or not path.is_file() for path in (scope_path,session_path)):raise ValueError('ScopeMissing')
    scope=json.loads(scope_path.read_text());state=json.loads(session_path.read_text())
    if (type(instance) is not int or instance<=0 or instance in (58690026,58716527)
            or any(value.get('project')!=PROJECT or value.get('label')!=PROJECT or value.get('instance_id')!=instance for value in (scope,state))
            or state.get('scope_sha256')!=sha(scope_path)):raise ValueError('ScopeMismatch')
    marker=ops/('request-logs-instance-'+str(instance)+'-dispatch.json')
    if marker.exists():return consume_existing(marker,instance,sha(scope_path),ops)
    if state.get('destroyed_epoch'):raise ValueError('Destroyed instance; no fresh log request')
    out.mkdir(exist_ok=False)
    result={'project':PROJECT,'instance_id':instance,'scope_sha256':sha(scope_path),'requested_at_utc':utc(),
            'method':'PUT','endpoint':'/api/v0/instances/request_logs/'+str(instance)+'/',
            'payload':{'tail':'1000','daemon_logs':False},'completed':False,'failure':None,
            'put_replays':0,'get_readiness_max_seconds':45,'get_attempts':[],
            'raw_logs_or_result_url_persisted':False}
    # Global exclusive marker prevents replay after an unknown PUT outcome.
    write_new(marker,{**result,'evidence_directory':str(out)})
    write_new(out/'dispatch.json',result)
    try:
        response=request(instance);result['api_http_status']=response['http_status']
        started=clock();until=started+45;last_error=None
        sleep(3)
        while clock()<until:
            probe={'attempt':len(result['get_attempts'])+1,'elapsed_s':round(clock()-started,3)}
            try:
                status,raw=fetch(response['result_url'],timeout=min(10,until-clock()))
                probe['http_status']=status;last_error=None
            except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError) as error:
                probe['failure_class']=type(error).__name__
                probe['http_status']=error.code if isinstance(error,urllib.error.HTTPError) else None
                if isinstance(error,urllib.error.HTTPError):error.close()
                last_error=error
            result['get_attempts'].append(probe)
            with (out/'get-probes.jsonl').open('a') as stream:stream.write(json.dumps(probe)+'\n');stream.flush()
            if last_error is None:break
            sleep(min(3,max(0,until-clock())))
        if last_error is not None:raise last_error
        if not result['get_attempts']:raise TimeoutError()
        result['object_http_status']=status
        projection=project(raw)
        safe,redactions=sanitize(raw)
        with (out/'container-sanitized.log').open('x') as stream:
            stream.write(safe)
        write_new(out/'container-findings.json',projection)
        result.update(projection,completed=True,sanitized_log_sha256=sha(out/'container-sanitized.log'),
                      sanitized_log_format='full_redacted_text_v2',redaction_statistics=redactions,
                      findings_sha256=sha(out/'container-findings.json'))
    except BaseException as error:
        result['failure']={'class':type(error).__name__,'http_status':error.code if isinstance(error,urllib.error.HTTPError) else None}
    result['finished_at_utc']=utc();write_new(out/'receipt.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instance-id',required=True,type=int);parser.add_argument('--out',required=True)
    args=parser.parse_args();value=collect(args.instance_id,args.out)
    print(json.dumps(value));return int(not value['completed'])


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:raise SystemExit('Log collection failed: '+type(error).__name__) from None
