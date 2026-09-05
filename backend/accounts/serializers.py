from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from accounts.models import UserProfile
from accounts.permissions import ALL_TABS, AccessLevel, PERMANENT_ADMIN_USERNAME, allowed_tabs_for_user, full_tab_permissions, tab_permissions_for_user


VALID_ACCESS_LEVELS = {AccessLevel.NONE, AccessLevel.VIEW, AccessLevel.FULL}


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        request = self.context.get('request')
        user = authenticate(request=request, username=attrs['username'], password=attrs['password'])
        if user is None:
            raise serializers.ValidationError('Invalid username or password.')
        if not user.is_active:
            raise serializers.ValidationError('This user account is inactive.')
        attrs['user'] = user
        return attrs


class UserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    is_superuser = serializers.BooleanField()
    full_name = serializers.SerializerMethodField()
    access_tabs = serializers.SerializerMethodField()
    tab_permissions = serializers.SerializerMethodField()
    is_permanent_admin = serializers.SerializerMethodField()

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username

    def get_access_tabs(self, obj):
        return allowed_tabs_for_user(obj)

    def get_tab_permissions(self, obj):
        return tab_permissions_for_user(obj)

    def get_is_permanent_admin(self, obj):
        return obj.username == PERMANENT_ADMIN_USERNAME


class ManagedUserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    password = serializers.CharField(write_only=True, required=False, trim_whitespace=False)
    tab_permissions = serializers.DictField(write_only=True, required=False)
    access_tabs = serializers.SerializerMethodField()
    effective_tab_permissions = serializers.SerializerMethodField()
    is_permanent_admin = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name', 'is_active',
            'is_superuser', 'full_name', 'access_tabs', 'tab_permissions',
            'effective_tab_permissions', 'is_permanent_admin', 'password',
            'date_joined', 'last_login',
        ]
        read_only_fields = [
            'id', 'is_superuser', 'full_name', 'access_tabs',
            'effective_tab_permissions', 'is_permanent_admin',
            'date_joined', 'last_login',
        ]

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username

    def get_access_tabs(self, obj):
        return allowed_tabs_for_user(obj)

    def get_effective_tab_permissions(self, obj):
        return tab_permissions_for_user(obj)

    def get_is_permanent_admin(self, obj):
        return obj.username == PERMANENT_ADMIN_USERNAME

    def validate_username(self, value):
        queryset = User.objects.filter(username__iexact=value)
        if self.instance is not None:
            queryset = queryset.exclude(id=self.instance.id)
        if queryset.exists():
            raise serializers.ValidationError('A user with this username already exists.')
        return value

    def validate_password(self, value):
        validate_password(value, self.instance)
        return value

    def validate_tab_permissions(self, value):
        cleaned = {}
        for tab, level in value.items():
            if tab not in ALL_TABS:
                raise serializers.ValidationError(f'{tab} is not a valid tab.')
            if level not in VALID_ACCESS_LEVELS:
                raise serializers.ValidationError(f'{level} is not a valid access level.')
            cleaned[tab] = level
        return cleaned

    def validate(self, attrs):
        if self.instance and self.instance.username == PERMANENT_ADMIN_USERNAME:
            raise serializers.ValidationError('Digi7 Admin is a permanent account and cannot be edited.')
        return attrs

    def create(self, validated_data):
        tab_permissions = validated_data.pop('tab_permissions', None)
        password = validated_data.pop('password', None)
        if not password:
            raise serializers.ValidationError({'password': 'Password is required when creating a user.'})
        user = User(
            email='',
            is_staff=False,
            is_superuser=False,
            **validated_data,
        )
        user.set_password(password)
        user.save()
        UserProfile.objects.update_or_create(
            user=user,
            defaults={'tab_permissions': self._normalized_permissions(tab_permissions), 'allowed_tabs': []},
        )
        return user

    def update(self, instance, validated_data):
        tab_permissions = validated_data.pop('tab_permissions', None)
        password = validated_data.pop('password', None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.email = ''
        instance.is_staff = False
        if password:
            instance.set_password(password)
        instance.save()
        if tab_permissions is not None:
            UserProfile.objects.update_or_create(
                user=instance,
                defaults={'tab_permissions': self._normalized_permissions(tab_permissions), 'allowed_tabs': []},
            )
        return instance

    def _normalized_permissions(self, tab_permissions):
        permissions = {tab: AccessLevel.NONE for tab in sorted(ALL_TABS)}
        permissions.update(tab_permissions or {})
        return permissions


def enforce_permanent_admin(user):
    if user.username != PERMANENT_ADMIN_USERNAME:
        return
    changed_fields = []
    if not user.is_active:
        user.is_active = True
        changed_fields.append('is_active')
    if not user.is_staff:
        user.is_staff = True
        changed_fields.append('is_staff')
    if not user.is_superuser:
        user.is_superuser = True
        changed_fields.append('is_superuser')
    if changed_fields:
        user.save(update_fields=changed_fields)
    UserProfile.objects.update_or_create(
        user=user,
        defaults={'tab_permissions': full_tab_permissions(), 'allowed_tabs': []},
    )
