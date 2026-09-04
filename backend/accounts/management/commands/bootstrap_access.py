import os

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError

from accounts.permissions import Roles


class Command(BaseCommand):
    help = 'Create or update production access users from environment variables.'

    def handle(self, *args, **options):
        client_password = os.environ.get('DIGI7_CLIENT_PASSWORD')
        superadmin_password = os.environ.get('DIGI7_SUPERADMIN_PASSWORD')

        if not client_password or not superadmin_password:
            raise CommandError(
                'DIGI7_CLIENT_PASSWORD and DIGI7_SUPERADMIN_PASSWORD are required.'
            )

        groups = {
            role: Group.objects.get_or_create(name=role)[0]
            for role in [Roles.ADMIN, Roles.OPERATIONS, Roles.FINANCE, Roles.GATEKEEPER]
        }

        client = self._upsert_user(
            username=os.environ.get('DIGI7_CLIENT_USERNAME', 'syed.zulfiqar'),
            password=client_password,
            first_name=os.environ.get('DIGI7_CLIENT_FIRST_NAME', 'Syed'),
            last_name=os.environ.get('DIGI7_CLIENT_LAST_NAME', 'Zulfiqar'),
            email=os.environ.get('DIGI7_CLIENT_EMAIL', 'syed.zulfiqar@digi7.org'),
            is_superuser=False,
            is_staff=True,
        )
        client.groups.set([groups[Roles.ADMIN]])

        superadmin = self._upsert_user(
            username=os.environ.get('DIGI7_SUPERADMIN_USERNAME', 'digi7.superadmin'),
            password=superadmin_password,
            first_name=os.environ.get('DIGI7_SUPERADMIN_FIRST_NAME', 'Digi7'),
            last_name=os.environ.get('DIGI7_SUPERADMIN_LAST_NAME', 'Superadmin'),
            email=os.environ.get('DIGI7_SUPERADMIN_EMAIL', 'admin@digi7.org'),
            is_superuser=True,
            is_staff=True,
        )
        superadmin.groups.set([groups[Roles.ADMIN]])

        self.stdout.write(self.style.SUCCESS('Production access users are ready.'))

    def _upsert_user(
        self,
        *,
        username,
        password,
        first_name,
        last_name,
        email,
        is_superuser,
        is_staff,
    ):
        user, _ = User.objects.get_or_create(username=username)
        user.first_name = first_name
        user.last_name = last_name
        user.email = email
        user.is_active = True
        user.is_staff = is_staff
        user.is_superuser = is_superuser
        user.set_password(password)
        user.save()
        return user
