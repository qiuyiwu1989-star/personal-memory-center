"""python3 -m pipeline.memory_center [--port 5077] [--worker-only]"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
from .core import Store
from .model import Model, load_private_model_config
from .web import load_grants, local_app, start_worker


def main():
    parser = argparse.ArgumentParser(description='私有记忆中心本地首版')
    parser.add_argument('--port', type=int, default=5077)
    parser.add_argument('--worker-only', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    store = Store(os.environ.get('QIU_MEMORY_DATA_DIR', str(Path.home() / '.local/share/personal-memory-center')))
    grants_path = Path(os.environ.get('QIU_MEMORY_GRANTS', str(store.directory / 'grants.json')))
    if not grants_path.exists():
        token = secrets.token_urlsafe(32)
        grants_path.write_text(json.dumps([{'id': 'local-owner', 'owner': 'local-owner',
              'scopes': ['personal', 'project:demo'], 'actions': ['read', 'write'], 'trusted_user': True,
              'token_sha256': hashlib.sha256(token.encode()).hexdigest()}]))
        grants_path.chmod(0o600)
        (store.directory / 'owner-token.txt').write_text(token)
        (store.directory / 'owner-token.txt').chmod(0o600)
    load_private_model_config(store.directory / 'model.json')
    grants, model = load_grants(grants_path), Model()
    stop = start_worker(store, model)
    print('私有数据目录:', store.directory)
    print('本机工作台：打开即用，无需输入专用凭据')
    print('模型状态:', '已配置' if model.configured else '未配置；材料可归档，提炼会显示失败并可重试')
    try:
        if args.worker_only:
            while True:
                time.sleep(1)
        else:
            owner = next((p for p in grants if p['id'] == 'local-owner' and p.get('trusted_user')), None)
            local_app(store, grants, model, auto_principal=owner).run(host='127.0.0.1', port=args.port, debug=False, use_reloader=False, load_dotenv=False)
    finally:
        stop.set()


if __name__ == '__main__':
    main()
