import re

from opencc import OpenCC


# Keep these terms consistent across the menus, dialogue, and manual.
# Keys use the spelling produced by OpenCC. Menu labels must fit the original slots.
TERMS = {
    '选单': '菜单',
    '视窗': '窗口',
    '设定': '设置',
    '队型': '阵型',
    '设定自订队型': '自定义阵型',
    '自订': '自定义',
    '时间经过': '推进时间',
    '从头开始': '新游戏',
    '初学者': '新手',
    '呼叫援军': '请求援军',
    '开场部队指令': '初始部队指令',
    '量表显示': '条形显示',
    '除去标记': '清除标记',
    '标示队长': '标记队长',
    '全员标示': '标记全员',
    '丢掉弓箭': '丢弃弓箭',
    '金币已取得': '获得金币',
    '复活之药': '复活药',
    '体力回复药': '体力恢复药',
    '回复率': '恢复率',
    '矢防御力': '箭矢防御',
    '矢回避率': '箭矢闪避',
    '目前': '当前',
    '鼠标游标': '鼠标光标',
    '滑鼠': '鼠标',
    '游标': '光标',
    '捲动': '滚动',
    '卷动': '滚动',
    '拖曳': '拖动',
    '图示': '图标',
    '解析度': '分辨率',
    '档案': '文件',
    '载入': '加载',
    '执行绪': '线程',
    '物件': '对象',
    '全萤幕': '全屏',
    '萤幕': '屏幕',
    '预设': '默认',
    '开启音效，关闭音效特效': '开启音效，关闭特效',
    '开启音效与音效特效': '开启音效与特效',
    '关闭音效特效': '关闭特效',
    '重设': '重置',
    '点选': '点击',
}

_converter = OpenCC('tw2s')
_terms = re.compile('|'.join(re.escape(word) for word in sorted(TERMS, key=len, reverse=True)))


def simplify(text):
    return _terms.sub(lambda match: TERMS[match[0]], _converter.convert(text))
