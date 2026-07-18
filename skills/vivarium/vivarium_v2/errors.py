class VivariumError(Exception):
    exit_code = 2


class IntegrityError(VivariumError):
    exit_code = 3


class PolicyError(VivariumError):
    exit_code = 4


class RecoveryRequired(VivariumError):
    exit_code = 5
