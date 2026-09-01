"""TOUPAC Geo — ViewSets DRF."""
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.db.models import Q
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Place, Zone
from .serializers import (
    NearbyPlaceSerializer,
    PlaceCreateSerializer,
    PlaceDetailSerializer,
    PlaceListSerializer,
    ZoneCreateSerializer,
    ZoneSerializer,
)

_TAG = extend_schema(tags=["Geo"])


@extend_schema_view(
    list=_TAG, retrieve=_TAG, create=_TAG, update=_TAG, partial_update=_TAG, destroy=_TAG,
    nearby=_TAG,
)
class PlaceViewSet(viewsets.ModelViewSet):
    queryset = Place.objects.none()
    filterset_fields = ["type", "city", "country_code"]
    search_fields = ["name", "address", "city"]
    ordering = ["name"]

    def get_queryset(self):
        # Les places tenant=NULL sont partagées (gares publiques).
        return Place.objects.filter(Q(tenant=self.request.tenant) | Q(tenant__isnull=True))

    def get_serializer_class(self):
        if self.action == "list":
            return PlaceListSerializer
        if self.action == "retrieve":
            return PlaceDetailSerializer
        if self.action in ("create", "update", "partial_update"):
            return PlaceCreateSerializer
        return PlaceDetailSerializer

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @action(detail=False, methods=["get"], url_path="nearby")
    def nearby(self, request):
        """
        GET /geo/places/nearby/?lat=14.6937&lng=-17.4441&radius=10
        Retourne les lieux dans un rayon donné (km) d'un point, triés par distance.
        """
        lat = request.query_params.get("lat")
        lng = request.query_params.get("lng")
        radius_km = float(request.query_params.get("radius", 10))

        if not lat or not lng:
            return Response({"detail": "Paramètres lat et lng requis."}, status=status.HTTP_400_BAD_REQUEST)

        point = Point(float(lng), float(lat), srid=4326)
        places = (
            self.get_queryset()
            .filter(location__dwithin=(point, D(km=radius_km)))
            .annotate(distance=Distance("location", point))
            .order_by("distance")
        )

        serializer = NearbyPlaceSerializer(places, many=True)
        return Response(serializer.data)


@extend_schema_view(
    list=_TAG, retrieve=_TAG, create=_TAG, update=_TAG, partial_update=_TAG, destroy=_TAG,
)
class ZoneViewSet(viewsets.ModelViewSet):
    queryset = Zone.objects.none()
    filterset_fields = ["type", "is_active"]
    search_fields = ["name"]

    def get_queryset(self):
        return Zone.objects.filter(tenant=self.request.tenant)

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return ZoneCreateSerializer
        return ZoneSerializer

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)
