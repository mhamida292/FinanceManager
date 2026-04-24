from apps.banking.managers import UserScopedQuerySet


class InvestmentAccountQuerySet(UserScopedQuerySet):
    def for_user(self, user):
        return self.filter(user=user)


class HoldingQuerySet(UserScopedQuerySet):
    def for_user(self, user):
        return self.filter(investment_account__user=user)


class PortfolioSnapshotQuerySet(UserScopedQuerySet):
    def for_user(self, user):
        return self.filter(investment_account__user=user)
