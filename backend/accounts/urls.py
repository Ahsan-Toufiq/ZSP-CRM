from django.urls import include, path
from rest_framework.routers import DefaultRouter

from accounts.views import LoginView, LogoutView, ManagedUserViewSet, MeView, csrf

router = DefaultRouter()
router.register('users', ManagedUserViewSet, basename='user')

urlpatterns = [
    path('csrf/', csrf, name='csrf'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('me/', MeView.as_view(), name='me'),
    path('', include(router.urls)),
]
