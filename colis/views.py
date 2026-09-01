"""TOUPAC Colis — ViewSets DRF."""
from django.contrib.gis.geos import Point
from django.db.models import Count
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DeliveryTask, Order, Parcel, ProofOfDelivery
from .serializers import (
    DeliveryTaskSerializer,
    DispatchRequestSerializer,
    OrderCreateSerializer,
    OrderDetailSerializer,
    OrderListSerializer,
    ParcelCreateSerializer,
    ParcelSerializer,
    ProofOfDeliveryCreateSerializer,
    ProofOfDeliverySerializer,
)
from .services import DispatchService, InternalIdGenerator, TrackingNumberGenerator

_TAG = extend_schema(tags=["Colis"])
_CRUD_TAGS = {
    "list": _TAG, "retrieve": _TAG, "create": _TAG,
    "update": _TAG, "partial_update": _TAG, "destroy": _TAG,
}


@extend_schema_view(**_CRUD_TAGS, add_parcel=_TAG)
class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.none()
    filterset_fields = ["status", "priority", "payment_status"]
    search_fields = ["internal_id", "customer_name", "customer_phone"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return (
            Order.objects.filter(tenant=self.request.tenant)
            .select_related("customer", "pickup_place", "dropoff_place", "created_by")
            .annotate(parcel_count=Count("parcels"))
        )

    def get_serializer_class(self):
        if self.action == "list":
            return OrderListSerializer
        if self.action == "retrieve":
            return OrderDetailSerializer
        if self.action in ("create", "update", "partial_update"):
            return OrderCreateSerializer
        return OrderDetailSerializer

    def perform_create(self, serializer):
        serializer.save(
            tenant=self.request.tenant,
            created_by=self.request.user,
            internal_id=InternalIdGenerator.generate(self.request.tenant),
        )

    @action(detail=True, methods=["post"], url_path="parcels")
    def add_parcel(self, request, pk=None):
        """POST /colis/orders/{id}/parcels/ — ajoute un colis à la commande."""
        order = self.get_object()
        serializer = ParcelCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        parcel = serializer.save(
            tenant=request.tenant,
            order=order,
            tracking_number=TrackingNumberGenerator.generate(),
        )
        return Response(ParcelSerializer(parcel).data, status=status.HTTP_201_CREATED)


@extend_schema_view(list=_TAG, retrieve=_TAG)
class ParcelViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ParcelSerializer
    queryset = Parcel.objects.none()
    search_fields = ["tracking_number", "description"]
    filterset_fields = ["status", "category", "order"]

    def get_queryset(self):
        return Parcel.objects.filter(tenant=self.request.tenant).select_related("order")


@extend_schema_view(**_CRUD_TAGS, pod=_TAG)
class DeliveryTaskViewSet(viewsets.ModelViewSet):
    serializer_class = DeliveryTaskSerializer
    queryset = DeliveryTask.objects.none()
    filterset_fields = ["status", "type", "driver", "order"]
    ordering = ["sequence_order"]

    def get_queryset(self):
        return (
            DeliveryTask.objects.filter(tenant=self.request.tenant)
            .select_related("order", "driver__user", "vehicle", "place")
        )

    @action(detail=True, methods=["post"])
    def pod(self, request, pk=None):
        """POST /colis/delivery-tasks/{id}/pod/ — capture une preuve de livraison."""
        task = self.get_object()
        serializer = ProofOfDeliveryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        gps_data = serializer.validated_data.pop("gps_location", None)
        gps_point = None
        if gps_data:
            gps_point = Point(gps_data["lng"], gps_data["lat"], srid=4326)

        pod = ProofOfDelivery.objects.create(
            tenant=request.tenant,
            delivery_task=task,
            gps_location=gps_point,
            **serializer.validated_data,
        )

        task.status = DeliveryTask.Status.COMPLETED
        task.completed_at = timezone.now()
        task.save(update_fields=["status", "completed_at", "updated_at"])

        order = task.order
        all_tasks_done = not order.delivery_tasks.exclude(status=DeliveryTask.Status.COMPLETED).exists()
        if all_tasks_done:
            order.status = Order.Status.DELIVERED
            order.save(update_fields=["status", "updated_at"])

        return Response(ProofOfDeliverySerializer(pod).data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["Colis"],
    request=DispatchRequestSerializer,
    responses=inline_serializer("DispatchResponse", {
        "tasks_created": serializers.IntegerField(),
        "tasks": DeliveryTaskSerializer(many=True),
    }),
)
class DispatchView(APIView):
    """POST /api/v1/colis/dispatch/optimize/ — dispatch les commandes à un chauffeur."""

    def post(self, request):
        serializer = DispatchRequestSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        tasks = DispatchService.dispatch_orders(
            tenant=request.tenant,
            order_ids=serializer.validated_data["order_ids"],
            driver_id=serializer.validated_data["driver_id"],
            vehicle_id=serializer.validated_data["vehicle_id"],
        )
        return Response({
            "tasks_created": len(tasks),
            "tasks": DeliveryTaskSerializer(tasks, many=True).data,
        }, status=status.HTTP_201_CREATED)
