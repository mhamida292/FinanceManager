from django.db import models


class UserScopedQuerySet(models.QuerySet):
    """Base QuerySet for user-owned rows. Subclasses override ``for_user`` to
    filter through whatever FK chain reaches ``User``.

    Views MUST call ``Model.objects.for_user(request.user)`` before returning
    or serializing user data. A non-skippable test per app verifies that two
    users cannot see each other's rows.
    """

    def for_user(self, user):
        raise NotImplementedError(
            f"Subclasses of UserScopedQuerySet must override for_user(). "
            f"Missing on {type(self).__name__}."
        )
