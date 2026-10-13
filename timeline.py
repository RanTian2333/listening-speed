"""Shared timing rules for independent pause editing and offline export."""
import math


def validate_pause(pause):
    mode = pause.get('mode', 'off')
    if mode not in ('off', 'keep', 'ratio', 'fixed', 'cap'):
        raise ValueError('停顿调整方式无效。')
    value = float(pause.get('value', 1))
    maximum = 20 if mode == 'ratio' else 120
    if not math.isfinite(value) or not 0 <= value <= maximum:
        raise ValueError('停顿倍数范围为 0～20，秒数范围为 0～120。')
    return {'mode': mode, 'value': value}


def gap_duration(length, speed, pause, excluded=False):
    if excluded or pause['mode'] == 'off':
        return length / speed
    if pause['mode'] == 'keep':
        return length
    if pause['mode'] == 'ratio':
        # Independent of speaking rate: 1× retains the original pause seconds.
        return length * pause['value']
    if pause['mode'] == 'fixed':
        return pause['value']
    return min(length, pause['value'])


def build_plan(duration, gaps, speed, pause, excluded=()):
    segments, cursor, output = [], 0.0, 0.0
    def add(start, end, length, index=None, silent=False):
        nonlocal output
        segments.append(dict(sourceStart=start, sourceEnd=end, start=output,
                             end=output + length, gap=index, silent=silent))
        output += length
    for index, (start, end) in enumerate(gaps):
        if start > cursor:
            add(cursor, start, (start - cursor) / speed)
        length = gap_duration(end - start, speed, pause, index in excluded)
        add(start, end, length, index, abs(length - (end-start)/speed) > 1e-6)
        cursor = end
    if duration > cursor:
        add(cursor, duration, (duration - cursor) / speed)
    return {'segments': segments, 'duration': output}


def export_parts(plan):
    """Merge continuous source audio; only modified gaps become synthetic silence."""
    parts = []
    for segment in plan['segments']:
        part = segment.copy()
        if not part['silent'] and parts and not parts[-1]['silent']:
            parts[-1]['sourceEnd'] = part['sourceEnd']
            parts[-1]['end'] = part['end']
        else:
            parts.append(part)
    return parts
