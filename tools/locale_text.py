import re


# In these slots the DOS pointer aliases a different scene or has no counterpart.
# 18 repairs a stray 89 E4 pair before the valid Big5 for 讓.
STORY_CHANGES = {
    12: '宙：「塞內爾，你的本領又精進了。人世間已沒有人能與你的魔力匹敵。」',
    152: '吸血鬼：「呃……真是一群難纏的傢伙。我要吸乾你們身上的血！」',
    407: '魔人：「吾乃受召自地獄而來，為封印妖精王而現身。凡靠近吾者，必遭毀滅！」',
    408: '魔人：「呃……真是一群難纏的傢伙。」',
    409: '魔人：「呃、啊……竟能把我逼到這個地步！你們就不怕我的力量嗎？」',
    548: '「你們正在與波斯交戰吧？在插手我們的事以前，難道沒有更要緊的事要做嗎？」',
    549: '士兵：「只要貝尼塔城與馬西亞城還在，我城就固若金湯。回去吧！」',
    559: '利斯萊姆：「若需要援軍，請在選單中選擇〔呼叫援軍〕。同一地區或鄰近地區的部隊都能前來增援。」',
    648: '士兵：「法蘭克派來的部隊已在外等候，請您前去接見！」',
    649: '牆壁的一部分打開了！',
    651: '牆壁的一部分打開了！',
    798: '「裡面什麼也沒有。」',
}

JP_ESCAPE = re.compile(r'\\P[0-9A-F]R?')

# Inline event text in the Windows map bank, outside the indexed story table.
FQFBANK_TEXT = {
    0x9A5B: (
        '　' * 8 + '道士レクス' + '　' * 15 + '勇者グラン' + '　' * 7,
        '　' * 8 + '雷克斯　魔法師兵團'.ljust(20, '　') + '葛南　騎士兵團',
    ),
    0xCB5B: (
        'なあに、今はゼネルに協力しているが、あいつの力を利用するだけしたら寝首をかいてやるさ」',
        '哼，我現在是和塞內爾合作。等他的力量派不上用場了，我就趁他熟睡時下手！」',
    ),
}


def localize_story(row, convert=str):
    idx, jp, zh = (row[key] for key in ('id', 'ja', 'zh'))
    if idx == 799:
        return jp, 'engine-table'
    if idx in STORY_CHANGES:
        text, origin = STORY_CHANGES[idx], 'windows'
    elif idx == 18:
        raw = bytes.fromhex(row['dos_hex'])
        assert raw.count(b'\x02\x89\xe4\xc5\xfd') == 1
        text = raw.replace(b'\x02\x89\xe4\xc5\xfd', b'\x02\xc5\xfd').decode('cp950')
        origin = 'dos-repaired'
    else:
        text, origin = zh.strip(), 'dos'

    text = convert(text)
    if jp.count('\x01') == 2 and not jp.startswith('「'):
        choices = re.split(r'\u3000{3,}', text)
        assert len(choices) == 3, (idx, choices)
        text = '\x01\u3000\u3000'.join(choices)
    if jp.startswith('\t'):
        text = '\t' + text

    pages = text.split('\x02')
    for number, japanese_page in enumerate(jp.split('\x02')):
        for escape in JP_ESCAPE.finditer(japanese_page):
            page = min(number, len(pages) - 1)
            start = pages[page].find('「') + 1 if page == 0 else 0
            pages[page] = pages[page][:start] + escape[0] + pages[page][start:]

    # Bound the 24-column message window. Long DOS passages get a continuation
    # page, while DOS page breaks and the Windows choice rows stay intact.
    if '\x01' not in text:
        for index, p in enumerate(pages):
            if len(JP_ESCAPE.sub('', p).lstrip('\t')) > 120:
                cut = max(p.rfind(mark, 65, 117) for mark in '。！？；，') + 1
                if cut == 0:
                    cut = 108
                pages[index] = p[:cut] + '\x02' + p[cut:]
    return '\x02'.join(pages), origin


EFFECT_CHANGES = {
    1: '短劍', 2: '長劍', 3: '冰劍', 4: '烈火劍', 5: '威力強，但會降低防禦',
    6: '偶爾使敵我雙方瀕死', 7: '偶爾使使用者混亂', 8: '偶爾使使用者受傷',
    11: '威力強，但會降低防禦', 17: '長槍', 18: '有突刺的長槍',
    20: '有機會發出致命一擊', 21: '大型戰斧', 22: '將對方擊飛', 23: '打擊武器',
    25: '縮短施放魔法的間隔', 30: '以鎖環製成的輕鎧', 31: '堅固的鎧甲',
    33: '堅固的全身鎧甲', 34: '也能提高防禦率的鎧甲', 37: '也能提高攻擊力的鎧甲',
    41: '提高防禦率的戒指', 42: '大幅提高防禦率的戒指', 43: '提高攻擊率和防禦率',
    44: '提高攻擊率的戒指', 67: '給馬使用可提高基本攻擊率',
    69: '使用後可消除疲勞', 70: '使用後可解除我軍中毒',
}

HARD_EFFECTS = {
    16: '使使用者較不易疲勞', 25: '稍微縮短施放魔法的間隔',
    38: '敵人較不易鎖定使用者', 46: '加強對火屬性敵人的防禦',
    47: '加強對土屬性敵人的防禦', 48: '加強對風屬性敵人的防禦',
    49: '加強對水屬性敵人的防禦',
}


def localize_table(row):
    kind, idx, ja, zh = (row[key] for key in ('kind', 'id', 'ja', 'zh'))
    if not ja:
        return '', 'blank'
    if kind in ('effect', 'effect_hard'):
        if kind == 'effect_hard' and idx in HARD_EFFECTS:
            return HARD_EFFECTS[idx], 'windows-hard'
        if idx in EFFECT_CHANGES:
            return EFFECT_CHANGES[idx], 'windows'
    if kind.startswith('spell'):
        overrides = {40: '石化', 41: '混亂', 42: '讀心術', 43: '？？？'}
        if idx in overrides:
            return overrides[idx], 'dos-term' if idx == 42 else 'windows'
    if kind == 'person':
        if idx in (652, 656, 657):
            return {652: '解僱', 656: '新部隊', 657: '自由視窗'}[idx], 'windows'
        if 653 <= idx <= 655:
            return f'預備隊{idx - 652}', 'dos-layout'
    if zh:
        return zh, 'dos'
    raise ValueError(f'Untranslated table row {kind}:{idx} {ja}')
