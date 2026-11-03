#!/usr/bin/env python3
"""Explicit SSH/SCP wrapper bound to the new immutable Hard scope. No retries."""
import argparse
import ipaddress
import json
from pathlib import Path
import shlex
import subprocess
import sys

from inference_vast import Rental, ROOT, REPO

REMOTE_REPO = '/workspace/servedoctor-hard/servetune'


def connection(service=None):
    service = Rental() if service is None else service
    state = service.load()
    status = state.get('last_status', {})
    if (state.get('instance_id') in (58690026,58716527) or state.get('destroyed_epoch')
            or status.get('id') != state['instance_id'] or status.get('actual_status') != 'running'):
        raise ValueError('A new scoped running Hard rental is required')
    address = str(ipaddress.IPv4Address(status['public_ipaddr']))
    port = int(status['ports']['22/tcp'][0]['HostPort'])
    if not 1 <= port <= 65535: raise ValueError('Invalid scoped SSH port')
    known = service.root/'known_hosts'
    if known.is_symlink() or not known.is_file(): raise ValueError('Reviewed Hard known_hosts is required')
    identity = service.repo/'runs/vast-preflight-20261029/ssh_ed25519'
    # The identity is passed as a path only, never opened by this helper.
    options = ['-F','/dev/null','-i',str(identity),'-o','IdentitiesOnly=yes','-o','BatchMode=yes',
               '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile="'+str(known)+'"',
               '-o','ConnectionAttempts=1','-o','ConnectTimeout=15',
               '-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2']
    return options,address,port


def command(operation, arguments, service=None):
    options,address,port=connection(service)
    if operation == 'run':
        if arguments and arguments[0] == '--': arguments=arguments[1:]
        if not arguments: raise ValueError('Remote argv required')
        code = ("import os,resource; "
                "soft,hard=resource.getrlimit(resource.RLIMIT_NOFILE); "
                "assert hard==resource.RLIM_INFINITY or hard>=65536; "
                "resource.setrlimit(resource.RLIMIT_NOFILE,(65536,hard)); "
                f"os.chdir({REMOTE_REPO!r}); "
                f"argv={arguments!r}; os.execvp(argv[0],argv)")
        remote=['env','PATH=/venv/main/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                'HF_HOME=/workspace/.hf_home','HF_HUB_OFFLINE=1','TRANSFORMERS_OFFLINE=1',
                'HF_HUB_DISABLE_TELEMETRY=1','VLLM_NO_USAGE_STATS=1','VLLM_CACHE_ROOT=/workspace/.vllm_cache',
                '/venv/main/bin/python','-c',code]
        return ['ssh',*options,'-p',str(port),'root@'+address,shlex.join(remote)]
    if len(arguments)!=2: raise ValueError('SCP needs source and destination')
    source,destination=arguments
    if operation == 'put':
        if not Path(source).exists() or Path(source).is_symlink(): raise ValueError('Existing local source required')
        if not destination.startswith('/') or '\n' in destination: raise ValueError('Absolute remote destination required')
        return ['scp',*options,'-P',str(port),'-r',source,'root@'+address+':'+destination]
    if operation == 'get':
        if not source.startswith('/') or '\n' in source: raise ValueError('Absolute remote source required')
        if Path(destination).exists() or Path(destination).is_symlink(): raise ValueError('Fresh local copy destination required')
        return ['scp',*options,'-P',str(port),'-r','root@'+address+':'+source,destination]
    raise ValueError('Unknown remote operation')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['run','put','get']);parser.add_argument('arguments',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    return subprocess.run(command(args.operation,args.arguments)).returncode


if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception as exc: raise SystemExit('Hard SSH failed: '+type(exc).__name__) from None
