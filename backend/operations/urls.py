from rest_framework.routers import DefaultRouter

from operations.views import (
    AuctionSaleViewSet,
    ContainerItemViewSet,
    ContainerViewSet,
    CustomerViewSet,
    GatePassViewSet,
)

router = DefaultRouter()
router.register('customers', CustomerViewSet, basename='customer')
router.register('containers', ContainerViewSet, basename='container')
router.register('items', ContainerItemViewSet, basename='item')
router.register('auction-sales', AuctionSaleViewSet, basename='auction-sale')
router.register('gate-passes', GatePassViewSet, basename='gate-pass')

urlpatterns = router.urls
