"""Source coverage declaration; never an identity, permission or trust grant."""
import json
from .core import Invalid

FIELDS = {'original_ref', 'original_date', 'author', 'locator', 'parser_version',
          'parent_source_key', 'visibility'}
VISIBILITY = {'unknown', 'visible_only', 'complete_visible'}


def validate(metadata):
    if not isinstance(metadata, dict) or set(metadata) - FIELDS or any(
            not isinstance(v, str) or len(v) > 1000 for v in metadata.values()):
        raise Invalid('来源元信息无效；权限由服务端取得')
    if 'visibility' in metadata and metadata['visibility'] not in VISIBILITY:
        raise Invalid('来源可见性需为 unknown / visible_only / complete_visible')
    return dict(metadata)


def load(db, source_id):
    row = db.execute('SELECT metadata FROM source_envelopes WHERE source_id=?', (source_id,)).fetchone()
    if not row:
        return {}
    metadata = json.loads(row['metadata'])
    if not isinstance(metadata, dict):
        raise Invalid('已归档来源元信息格式无效')
    return metadata
