from sqlalchemy.exc import IntegrityError


def integrity_constraint_name(error: IntegrityError) -> str | None:
    original_error = error.orig
    while original_error is not None:
        constraint_name = getattr(original_error, "constraint_name", None)
        if constraint_name is None:
            constraint_name = getattr(
                getattr(original_error, "diag", None),
                "constraint_name",
                None,
            )
        if constraint_name is not None:
            return constraint_name
        original_error = original_error.__cause__ or original_error.__context__
    return None
