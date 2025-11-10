from rest_framework import generics, viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from django.shortcuts import get_object_or_404

from .models import Party, PartyMenuItem, Table, Seat, SeatSelection, Modifier, MenuItem
from .serializers import (
    PartyMenuItemSerializer,
    SeatSerializer,
    SeatSelectionSerializer,
    ModifierSerializer,
)
from rest_framework.permissions import IsAuthenticated

class IsStaffOrReadOnly(IsAuthenticated):
    def has_permission(self, request, view):
        # Staff can write; anyone logged in can read menu
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return request.user.is_authenticated
        return request.user.is_staff

# --------------------------------------------------------------
# 1️⃣  Party menu (filtered by availability)
# --------------------------------------------------------------
class PartyMenuView(generics.ListAPIView):
    permission_classes = [IsStaffOrReadOnly]
    serializer_class = PartyMenuItemSerializer

    def get_queryset(self):
        slug = self.kwargs["slug"]
        party = get_object_or_404(Party, slug=slug)
        return PartyMenuItem.objects.filter(party=party, available=True).select_related(
            "menu_item"
        ).prefetch_related("menu_item__modifiers")


# --------------------------------------------------------------
# 2️⃣  Seats for a given table
# --------------------------------------------------------------
class TableSeatsView(generics.ListAPIView):
    permission_classes = [IsStaffOrReadOnly]
    serializer_class = SeatSerializer

    def get_queryset(self):
        table_id = self.kwargs["table_id"]
        return Seat.objects.filter(table_id=table_id).prefetch_related(
            "seatselection_set__modifiers"
        )


# --------------------------------------------------------------
# 3️⃣  Cart actions (GET / POST / PATCH / DELETE)
# --------------------------------------------------------------
class SeatCartView(generics.ListCreateAPIView):
    permission_classes = [IsStaffOrReadOnly]
    serializer_class = SeatSelectionSerializer

    def get_queryset(self):
        seat_id = self.kwargs["seat_id"]
        return SeatSelection.objects.filter(seat_id=seat_id).prefetch_related(
            "modifiers"
        )

    def perform_create(self, serializer):
        seat = get_object_or_404(Seat, pk=self.kwargs["seat_id"])
        serializer.save(seat=seat)


class SeatSelectionDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsStaffOrReadOnly]
    serializer_class = SeatSelectionSerializer
    lookup_url_kwarg = "selection_id"

    def get_queryset(self):
        seat_id = self.kwargs["seat_id"]
        return SeatSelection.objects.filter(seat_id=seat_id)


# --------------------------------------------------------------
# 4️⃣  Submit the whole table as a formal Order
# --------------------------------------------------------------
@api_view(["POST"])
def submit_table_order(request):
    """
    Payload: { "table_id": <int> }
    Returns: { "order_id": <int>, "message": "created" }
    """
    table_id = request.data.get("table_id")
    table = get_object_or_404(Table, pk=table_id)

    # 1️⃣  Create a new Order linked to the party
    from .models import Order, Seat as SeatModel

    order = Order.objects.create(
        party=table.party,
        created_by=request.user,
        # any other required fields …
    )

    # 2️⃣  Copy every Seat + its selections into the permanent models
    for seat in table.seats.all():
        new_seat = SeatModel.objects.create(
            order=order,
            number=seat.number,
            table=seat.table,
        )
        for sel in seat.seatselection_set.all():
            new_sel = SeatSelection.objects.create(
                seat=new_seat,
                item=sel.item,
                # if you want to keep the overridden price:
                price=sel.price if hasattr(sel, "price") else None,
            )
            new_sel.modifiers.set(sel.modifiers.all())

    return Response({"order_id": order.id, "message": "created"}, status=status.HTTP_201_CREATED)