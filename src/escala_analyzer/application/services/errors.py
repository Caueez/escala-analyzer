"""Application failures with stable HTTP-independent semantics."""


class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass


class CapacityError(Exception):
    pass


class PreconditionError(ConflictError):
    pass
