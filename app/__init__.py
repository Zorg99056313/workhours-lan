# -*- coding: utf-8 -*-
"""
局域网工时统计系统
------------------------------------------------
把 vendor/openpyxl 加入模块搜索路径，这样目标电脑**不需要 pip install 任何东西**。
"""
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_vendor = os.path.join(os.path.dirname(_here), 'vendor')
if os.path.isdir(_vendor) and _vendor not in sys.path:
    sys.path.insert(0, _vendor)

__version__ = '1.0.0'
