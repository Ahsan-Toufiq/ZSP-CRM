from django.contrib.auth import authenticate
from django.contrib.auth.models import Group, User
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from accounts.models import UserProfile
from accounts.permissions import ALL_TABS, Roles, allowed_tabs_for_user, default_tabs_for_user


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
    email = serializers.EmailField()
    is_staff = serializers.BooleanField()
    is_superuser = serializers.BooleanField()
    full_name = serializers.SerializerMethodField()
    roles = serializers.SerializerMethodField()
    access_tabs = serializers.SerializerMethodField()

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username

    def get_roles(self, obj):
        return list(obj.groups.values_list('name', flat=True))

    def get_access_tabs(self, obj):
        return allowed_tabs_for_user(obj)


class ManagedUserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    roles = serializers.ListField(child=serializers.ChoiceField(choices=[
        Roles.ADMIN,
        Roles.OPERATIONS,
        Roles.FINANCE,
        Roles.GATEKEEPER,
    ]), write_only=True)
    access_tabs = serializers.ListField(child=serializers.ChoiceField(choices=sorted(ALL_TABS)), write_only=True)
    password = serializers.CharField(write_only=True, required=False, trim_whitespace=False)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name', 'email', 'is_active',
            'is_staff', 'is_superuser', 'full_name', 'roles', 'access_tabs',
            'password', 'date_joined', 'last_login',
        ]
        read_only_fields = ['id', 'is_superuser', 'full_name', 'date_joined', 'last_login']

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['roles'] = list(instance.groups.values_list('name', flat=True))
        data['access_tabs'] = allowed_tabs_for_user(instance)
        return data

    def validate_username(self, value):
        queryset = User.objects.filter(username__iexact=value)
        if self.instance is not None:
            queryset = queryset.exclude(id=self.instance.id)
        if queryset.exists():
            raise serializers.ValidationError('A user with this username already exists.')
        return value

    def validate_email(self, value):
        if not value:
            return value
        queryset = User.objects.filter(email__iexact=value)
        if self.instance is not None:
            queryset = queryset.exclude(id=self.instance.id)
        if queryset.exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def validate_password(self, value):
        validate_password(value, self.instance)
        return value

    def validate_access_tabs(self, value):
        role_values = self.initial_data.get('roles')
        if role_values is None and self.instance is not None:
            role_values = list(self.instance.groups.values_list('name', flat=True))
        if 'users' in value and Roles.ADMIN not in (role_values or []):
            raise serializers.ValidationError('Only admin users can be given user-management access.')
        return sorted(set(value))

    def create(self, validated_data):
        roles = validated_data.pop('roles')
        access_tabs = validated_data.pop('access_tabs', None)
        password = validated_data.pop('password', None)
        if not password:
            raise serializers.ValidationError({'password': 'Password is required when creating a user.'})
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        self._sync_access(user=user, roles=roles, access_tabs=access_tabs)
        return user

    def update(self, instance, validated_data):
        roles = validated_data.pop('roles', None)
        access_tabs = validated_data.pop('access_tabs', None)
        password = validated_data.pop('password', None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:
            instance.set_password(password)
        instance.save()
        self._sync_access(user=instance, roles=roles, access_tabs=access_tabs)
        return instance

    def _sync_access(self, *, user, roles, access_tabs):
        if roles is not None:
            groups = [Group.objects.get_or_create(name=role)[0] for role in roles]
            user.groups.set(groups)
        if access_tabs is None:
            access_tabs = sorted(default_tabs_for_user(user))
        UserProfile.objects.update_or_create(user=user, defaults={'allowed_tabs': sorted(set(access_tabs))})
