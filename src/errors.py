"""Public error contract shared by prediction and single-period optimization."""


class DispatchServiceError(RuntimeError):
    def __init__(self, http_status: int, error_code: str, detail: str):
        super().__init__(detail)
        self.http_status = int(http_status)
        self.error_code = error_code
        self.detail = detail
