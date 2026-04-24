from apps.banking.managers import UserScopedQuerySet


class AssetQuerySet(UserScopedQuerySet):
    def for_user(self, user):
        return self.filter(user=user)


class AssetPriceSnapshotQuerySet(UserScopedQuerySet):
    def for_user(self, user):
        return self.filter(asset__user=user)
