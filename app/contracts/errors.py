"""跨块可分类错误；transport 层负责把它们映射为旧错误 envelope。"""


class ContractError(Exception):
    """稳定接口错误基类。"""

    code = "contract_error"


class InvalidRequestError(ContractError):
    code = "invalid_request"


class ResourceUnavailableError(ContractError):
    code = "resource_unavailable"


class BusyError(ContractError):
    code = "busy"


class NotReadyError(ContractError):
    code = "not_ready"
