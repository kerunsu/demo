"""渐进迁移的 HTTP route adapter 位置。

首个切片仍由 ``app.py`` 保留旧装饰器；route adapter 通过 use case/presenter
接线，待契约等价测试稳定后再逐条移动装饰器。
"""
