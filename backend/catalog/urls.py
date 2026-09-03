from rest_framework.routers import DefaultRouter

from catalog.views import DropdownOptionViewSet

router = DefaultRouter()
router.register('dropdown-options', DropdownOptionViewSet, basename='dropdown-option')

urlpatterns = router.urls
