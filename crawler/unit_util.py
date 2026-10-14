"""院系名称导航标签；不推断报考资格或专业接收条件。"""
GROUPS = {'computer': '计算机', 'software': '软件', 'ai': '人工智能', 'cyber': '网络安全',
          'control': '自动化与控制', 'information': '电子信息交叉', 'other': '其他相关院系'}


def groups(name):
    terms = {'computer': ('计算机',), 'software': ('软件',), 'ai': ('人工智能', '智能学院', '智能科学'),
             'cyber': ('网络空间', '网安', '网络安全'), 'control': ('自动化', '控制'),
             'information': ('信息', '电子', '通信')}
    return [key for key, words in terms.items() if any(word in name for word in words)] or ['other']
