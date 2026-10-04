"""Offline scope observations, never a segmentation or approval decision.

Surface punctuation and names are review navigation aids. Neither a different
name nor a condition keyword establishes grammatical or semantic independence.
All offsets are Python Unicode string offsets into the original message.
"""
import re

from .modality import CONDITION, LIST

DIAGNOSTIC_VERSION = 'condition-scope-observations-v1'
_PROJECT = re.compile(r'项目\s+(?P<name>[A-Za-z][A-Za-z0-9_-]*)')
_REFERENCE = re.compile(r'它|其|上述|前述|这项|该项|两项|共同|均|都|同样|\b(?:it|these|both|same)\b', re.I)


def scope_observations(text):
    """Return source-bound evidence for a reviewer, with no executable ranges.

    Clauses deliberately split even inside quotations: these are just lossless
    display units, NOT evidence boundaries. Ambiguity stays explicit. There is
    no model, persistence, intent inference, permission or guard override.
    """
    conditions = [{'start': match.start(), 'end': match.end(),
                   'text': match.group()} for match in CONDITION.finditer(text)]
    project_mentions = [{'start': match.start(), 'end': match.end(),
                         'text': match.group(), 'surface_name': match['name']}
                        for match in _PROJECT.finditer(text)]
    boundaries = [0, *[match.end() for match in re.finditer(r'[。！？!?;；\n]', text)]]
    if boundaries[-1] != len(text):
        boundaries.append(len(text))
    units = [{'start': start, 'end': end, 'text': text[start:end],
              'condition_offsets': [dict(item) for item in conditions
                                    if start <= item['start'] < end]}
             for start, end in zip(boundaries, boundaries[1:]) if start < end]
    reasons = []
    if conditions:
        reasons.append('condition_present_scope_unresolved')
        if len({item['surface_name'] for item in project_mentions}) > 1:
            reasons.append('distinct_project_surface_names_not_independence')
        if _REFERENCE.search(text):
            reasons.append('possible_reference_dependency')
        if LIST.search(text) or re.search(r'[“”「」"\[\]【】]|说|表示|引述|转述|写道', text):
            reasons.append('quoted_or_grouped_context_requires_review')
        if any(not unit['condition_offsets'] for unit in units) and len(units) > 1:
            reasons.append('condition_free_display_unit_not_unconditional_evidence')
    return {'diagnostic_version': DIAGNOSTIC_VERSION,
            'condition_occurrences': conditions, 'project_surface_mentions': project_mentions,
            'display_units': units, 'reason_codes': reasons,
            'scope_relationship': 'not_established',
            'display_units_are_evidence_spans': False,
            'automatic_scope_release': False, 'quality_approved': False}
