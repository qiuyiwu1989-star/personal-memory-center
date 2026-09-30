"""Build a private, verified full-source archive. Never executes imported content."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tarfile


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def build(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if not source.is_dir() or output == source or source in output.parents:
        raise ValueError('Output must be outside the source directory')
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.chmod(0o700)
    entries = []
    for p in sorted(source.rglob('*')):
        if p.is_symlink():
            raise ValueError('Symbolic links are not supported')
        if p.is_file():
            entries.append({'path':p.relative_to(source).as_posix(), 'bytes':p.stat().st_size, 'sha256':sha256_file(p)})
    if not entries:
        raise ValueError('Source contains no files')
    manifest = {'format':'memory-archive-v1','files':entries,'file_count':len(entries),'total_bytes':sum(x['bytes'] for x in entries)}
    raw = json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2).encode()
    batch = hashlib.sha256(raw).hexdigest()
    folder = output / batch
    folder.mkdir(mode=0o700,exist_ok=True)
    manifest_path, archive_path = folder/'manifest.json', folder/'source.tar.gz'
    manifest_path.write_bytes(raw);manifest_path.chmod(0o600)
    fd = os.open(archive_path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600);os.close(fd)
    with tarfile.open(archive_path,'w:gz') as tf:
        for item in entries:
            tf.add(source/item['path'],arcname=item['path'],recursive=False)
    # Re-read every archived byte; changing source files fail closed before upload.
    with tarfile.open(archive_path,'r:gz') as tf:
        for item in entries:
            member = tf.getmember(item['path']);h=hashlib.sha256()
            with tf.extractfile(member) as f:
                for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
            if member.size!=item['bytes'] or h.hexdigest()!=item['sha256']:
                raise ValueError('Source changed during archiving; retry from a stable export')
    receipt={'batch_id':batch,'file_count':len(entries),'source_bytes':manifest['total_bytes'],
             'archive_bytes':archive_path.stat().st_size,'archive_sha256':sha256_file(archive_path),
             'manifest_sha256':batch,'directory':str(folder)}
    (folder/'receipt.json').write_text(json.dumps(receipt,indent=2));(folder/'receipt.json').chmod(0o600)
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source');parser.add_argument('output')
    args=parser.parse_args();print(json.dumps(build(args.source,args.output),ensure_ascii=False))
