from django.urls import path

from accounts.views import LoginView, LogoutView, MeView, csrf

urlpatterns = [
    path('csrf/', csrf, name='csrf'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('me/', MeView.as_view(), name='me'),
]
