from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    class Tab(models.TextChoices):
        DASHBOARD = 'dashboard', 'Dashboard'
        CUSTOMERS = 'customers', 'Customers and balances'
        CONTAINERS = 'containers', 'Containers and inventory'
        SALES = 'sales', 'Auction sales'
        CHEQUES = 'cheques', 'Cheques'
        SETTINGS = 'settings', 'Dropdown settings'
        USERS = 'users', 'Users'

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    allowed_tabs = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['user__username']

    def __str__(self) -> str:
        return f'{self.user.username} access profile'
