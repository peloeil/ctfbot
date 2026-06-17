class BotError(Exception):
    pass


class ConfigurationError(BotError):
    pass


class RepositoryError(BotError):
    pass


class ConflictError(RepositoryError):
    pass


class ServiceError(BotError):
    pass


class ExternalAPIError(ServiceError):
    pass
