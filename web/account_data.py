"""Strict parsers for observed account values. Unknown values remain unknown."""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
import re

SECTIONS = ('identity', 'currency', 'training', 'guild_skills')
SECTION_LABELS = {'identity':'角色资料','currency':'金币 / 银币','training':'修炼等级','guild_skills':'帮派技能'}


def amount(text):
    raw = str(text).strip()
    value = re.sub(r'\s+', '', raw).replace('，', ',').replace('．', '.')
    value = re.sub(r'^(?:金币|银币|余额)[：:]?', '', value)
    if re.fullmatch(r'\d{1,3}(?:[,，.]\d{3})+', value):
        return {'value':int(re.sub(r'[,，.]', '', value)), 'display':raw, 'approximate':False}
    if re.fullmatch(r'\d+', value):
        return {'value':int(value), 'display':raw, 'approximate':False}
    compact = re.fullmatch(r'(\d+(?:\.\d+)?)(万|亿)', value)
    if compact:
        number = Decimal(compact.group(1)) * (10000 if compact.group(2) == '万' else 100000000)
        return {'value':int(number), 'display':raw, 'approximate':True}
    return None


def one_number(items):
    values = [value for item in items if (value := amount(item.text)) is not None]
    unique = {value['value'] for value in values}
    return values[0] if len(unique) == 1 else None


def role_header(items):
    # 角色名和等级可能被 OCR 拆成多项，先拼起来再解析，避免把“69级”读成名字“6”、等级“9”。
    joined = ''.join(re.sub(r'\s+', '', item.text) for item in items)
    result = {'role_name': None, 'role_id': None, 'level': None}
    identity = re.search(r'ID[:：]?([0-9]{6,12})', joined, re.I)
    if identity:
        result['role_id'] = identity.group(1)
    header = re.search(r'([^\d]{1,12}?)(\d{1,3})级', joined)
    if header and 1 <= int(header.group(2)) <= 200:
        name = header.group(1).strip()
        if name:
            result['role_name'] = name
            result['level'] = int(header.group(2))
    return result


def level_value(text):
    clean = re.sub(r'\s+', '', text)
    match = re.fullmatch(r'(?:等级[:：]?|Lv\.?|LV\.?)?(\d{1,3})(?:级|/(\d{1,3}))?', clean)
    if not match:return None
    current = int(match.group(1));maximum=int(match.group(2)) if match.group(2) else None
    if current > 200 or maximum is not None and (maximum > 200 or current > maximum):return None
    return {'level':current, 'maximum':maximum}

TRAINING_NAMES = ('攻法修炼','物防修炼','法防修炼','抗封修炼','攻击修炼','法术修炼','防御修炼','抗法修炼',
                  '宠物攻法','宠物物防','宠物法防','宠物抗封')
GUILD_SKILL_NAMES = ('强身术','冥想','烹饪技巧','炼药','中药医理','打造技巧','裁缝技巧','炼金技巧',
                    '熔炼技巧','逃离技巧','追捕技巧','巧匠之术','强壮','神速','淬灵','健体','养生之道','健身术')


def skills_from_text(items, names):
    """Associate only explicit levels with nearby named skills, excluding costs and experience."""
    results=[]
    for item in items:
        clean=re.sub(r'\s+','',item.text)
        name=next((name for name in names if name in clean),None)
        if not name:continue
        x,y,w,h=item.box
        suffix=clean.split(name,1)[1].lstrip('：:')
        level=level_value(suffix)
        if level is None:
            candidates=[]
            for other in items:
                ox,oy,ow,oh=other.box
                # An explicit unit/ratio is required: an upgrade cost is never a level.
                if not re.search(r'级|等级|[Ll][Vv]|[/／]',other.text):continue
                candidate=level_value(other.text.replace('／','/'))
                if candidate and abs(oy+oh/2-(y+h/2))<45 and -40<ox-(x+w)<260:
                    candidates.append((abs(oy-y)+max(0,ox-x-w),candidate))
            if len(candidates)==1:level=candidates[0][1]
            elif candidates:
                candidates.sort(key=lambda candidate:candidate[0])
                if candidates[0][0]+20<candidates[1][0]:level=candidates[0][1]
        if level is not None:
            headings=[other for other in items if other.text.replace(' ','') in ('人物修炼','宠物修炼','召唤灵修炼')
                      and other.box[1]<=y and abs(other.box[0]-x)<400]
            group=min(headings,key=lambda other:abs(other.box[0]-x)+y-other.box[1]).text if headings else None
            results.append({'name':name,'group':group,**level})
    return list({(item['group'],item['name']):item for item in results}.values())
