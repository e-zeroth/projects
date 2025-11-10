# orders/urls.py
from django.urls import path
from . import views
from . import api_views

app_name = "orders"

urlpatterns = [

    # ------------------------------------------------------------------
    #  API endpoints (used by the front‑end / mobile app)
    # ------------------------------------------------------------------
    path(
        "api/parties/<slug:slug>/menu/",
        api_views.PartyMenuView.as_view(),
        name="api-party-menu",
    ),
    path(
        "api/tables/<int:table_id>/seats/",
        api_views.TableSeatsView.as_view(),
        name="api-table-seats",
    ),
    path(
        "api/seats/<int:seat_id>/cart/",
        api_views.SeatCartView.as_view(),
        name="api-seat-cart",
    ),
    path(
        "api/seats/<int:seat_id>/cart/<int:selection_id>/",
        api_views.SeatSelectionDetailView.as_view(),
        name="api-seat-selection-detail",
    ),
    path(
        "api/orders/submit/",
        api_views.submit_table_order,
        name="api-submit-order",
    ),

    # ------------------------------------------------------------------
    #  Staff login / logout (code‑only)
    # ------------------------------------------------------------------
    path("login/", views.staff_login, name="staff_login"),
    path("logout/", views.staff_logout, name="staff_logout"),

    # ------------------------------------------------------------------
    #  Room‑centric workflow
    # ------------------------------------------------------------------
    path("rooms/", views.room_dashboard, name="room_dashboard"),
    path("rooms/<int:room_id>/tables/", views.room_tables, name="room_tables"),

    # Consolidated ticket for a whole room (HTML version – auto‑opens print dialog)
    path("rooms/<int:room_id>/print/", views.print_room_ticket, name="print_room_ticket"),

    # ------------------------------------------------------------------
    #  Table‑level UI (the tablet view you see in the browser)
    # ------------------------------------------------------------------
    path(
        "table/<int:table_id>/",
        views.table_detail,
        name="table_detail",
    ),
    path(
        "table/<int:table_id>/start/",
        views.start_order,
        name="start_order",
    ),
    path(
        "table/<int:table_id>/join/",
        views.join_order,
        name="join_order",
    ),
    path(
        "order/<int:order_id>/close/",
        views.close_order,
        name="close_order",
    ),
    path(
        "order/<int:order_id>/seat/add/",
        views.add_seat,
        name="add_seat",
    ),
    path(
        "seat/<int:seat_id>/remove/",
        views.remove_seat,
        name="remove_seat",
    ),
    path(
        "selection/add/",
        views.add_selection,
        name="add_selection",
    ),
    path(
        "selection/<int:selection_id>/remove/",
        views.remove_selection,
        name="remove_selection",
    ),
    path(
        "order/<int:order_id>/print/",
        views.print_ticket,
        name="print_ticket",
    ),
    path(
    "order/<int:order_id>/print/",
    views.print_ticket,
    name="print_order"),
    # ------------------------------------------------------------------
    #  AJAX endpoint – move a SeatSelection between seats
    # ------------------------------------------------------------------
    path(
        "selection/move/",
        views.move_selection,
        name="move_selection",
    ),
]