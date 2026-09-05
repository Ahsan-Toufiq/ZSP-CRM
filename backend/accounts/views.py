from django.contrib.auth.models import User
from django.contrib.auth import login, logout
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.exceptions import AuthenticationFailed
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.permissions import AdminPermission, PERMANENT_ADMIN_USERNAME
from accounts.serializers import LoginSerializer, ManagedUserSerializer, UserSerializer, enforce_permanent_admin


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
@ensure_csrf_cookie
def csrf(request):
    return Response({'detail': 'CSRF cookie set.'})


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            raise AuthenticationFailed('Invalid username or password.')
        login(request, serializer.validated_data['user'])
        return Response(UserSerializer(serializer.validated_data['user']).data)


class LogoutView(APIView):
    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        if not request.user.is_authenticated:
            return Response({'authenticated': False})
        return Response(UserSerializer(request.user).data)


class ManagedUserViewSet(viewsets.ModelViewSet):
    serializer_class = ManagedUserSerializer
    permission_classes = [AdminPermission]
    filterset_fields = ['is_active']
    search_fields = ['username', 'first_name', 'last_name']
    ordering_fields = ['username', 'date_joined', 'last_login']

    def get_queryset(self):
        return User.objects.prefetch_related('groups').select_related('profile').order_by('username')

    def list(self, request, *args, **kwargs):
        for user in User.objects.filter(username=PERMANENT_ADMIN_USERNAME):
            enforce_permanent_admin(user)
        return super().list(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        user = self.get_object()
        if user.username == PERMANENT_ADMIN_USERNAME:
            enforce_permanent_admin(user)
            return Response({'detail': 'Digi7 Admin is permanent and cannot be edited.'}, status=status.HTTP_400_BAD_REQUEST)
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        if user.username == PERMANENT_ADMIN_USERNAME:
            enforce_permanent_admin(user)
            return Response({'detail': 'Digi7 Admin is permanent and cannot be deleted.'}, status=status.HTTP_400_BAD_REQUEST)
        if user.id == request.user.id:
            return Response({'detail': 'You cannot delete your own account.'}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)
