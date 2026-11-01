class BusinessError(Exception):
    status = 422
    code = "VALIDATION_ERROR"

    def __init__(self, detail):
        self.detail = detail
        super().__init__(detail)


class NotFoundError(BusinessError):
    status = 404
    code = "NOT_FOUND"


class ConflictError(BusinessError):
    status = 409
    code = "CONFLICT"
