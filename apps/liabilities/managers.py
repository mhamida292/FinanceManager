from apps.banking.managers import UserScopedQuerySet


class LiabilityQuerySet(UserScopedQuerySet):
    def for_user(self, user):
        return self.filter(user=user)
