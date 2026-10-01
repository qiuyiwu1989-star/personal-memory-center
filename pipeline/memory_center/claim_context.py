"""Source-derived context, distinct from asserted event time and project identity."""
from datetime import datetime
import re


def evidence_context(message,source_type):
    raw=message.get('created_at') or ''
    try:
        parsed=datetime.fromisoformat(raw.replace('Z','+00:00'))
        date=parsed.date().isoformat() if re.match(r'^\d{4}-\d{2}-\d{2}(?:T|$)',raw) else None
    except (ValueError,TypeError):date=None
    title=message.get('source_title') or None
    secondary=source_type=='imported_summary'
    return {'source_date':date,'date_role':'summary_update' if secondary else 'message_time',
            'event_time':None,'current_validity':'unknown',
            'conversation_title':title,'project_identity':None,
            'scope_policy':'secondary_source' if secondary else 'source_conversation',
            'relative_time_anchor':None if secondary else date}


def contains_immediate_command(statement):
    # Narrow imperative patterns; historical reports such as “开始了第六讲” do
    # not match. A rejected mixed claim can be resubmitted without the command.
    return bool(re.search(r'(?:开始|继续)(?:写|生成|输出|编写|撰写)|(?:要求|请|帮我)(?:结合.{0,20})?(?:重写|撰写|写一篇|写一个|生成|输出)|开始第[一二三四五六七八九十百\d]+(?:讲|章|节)|继续(?:下一|第[一二三四五六七八九十\d]+)(?:讲|章|节)',statement))


def statement_has_date(statement,date):
    if not date:return True
    if date in statement:return True
    year,month,day=map(int,date.split('-'))
    return bool(re.search(fr'{year}年0?{month}月0?{day}日',statement))
