# orders/views.py
"""
Views for the “orders” app – they power the tablet UI (templates/orders/table_view.html).

Each view ends with a redirect back to the table‑detail page so the user stays on
the same screen. Feel free to extend them with permission checks, logging, etc.
"""

from typing import Any

import datetime

from django.contrib import messages
from django.http import HttpResponseRedirect, HttpResponse, JsonResponse
from django.db import models, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods

from .decorators import staff_required
from .forms import StartOrderForm
from .models import (
    Room,
    Party,
    Table,
    Order,
    Seat,
    SeatSelection,
    MenuItem,
    Modifier,
    Temperature,
    StaffMember,
    StaffLog,
    PartyMenuItem,
)


# ----------------------------------------------------------------------
# 1️⃣ Staff login – code only
# ----------------------------------------------------------------------
def staff_login(request):
    if request.method == "POST":
        code = request.POST.get("code", "").strip()
        staff = None
        # Iterate because we cannot filter by the hashed code
        for member in StaffMember.objects.all():
            if member.check_code(code):
                staff = member
                break
        if staff:
            request.session["staff_id"] = staff.id
            request.session["staff_name"] = staff.name
            messages.success(request, f"Welcome, {staff.name}!")
            return redirect(reverse("orders:room_dashboard"))
        else:
            messages.error(request, "Invalid code – try again.")
            return redirect(reverse("orders:staff_login"))
    # GET – show the simple form
    return render(request, "orders/staff_login.html")


def staff_logout(request):
    request.session.flush()
    messages.info(request, "You have been logged out.")
    return redirect(reverse("orders:staff_login"))


# ----------------------------------------------------------------------
# 2️⃣ Room Dashboard – list all rooms
# ----------------------------------------------------------------------
@staff_required
def room_dashboard(request):
    rooms = Room.objects.all().prefetch_related("tables")
    # optional audit
    StaffLog.objects.create(
        staff_id=request.session["staff_id"], action="opened room dashboard"
    )
    return render(
        request,
        "orders/room_dashboard.html",
        {"rooms": rooms, "staff_name": request.session.get("staff_name")},
    )


# ----------------------------------------------------------------------
# 3️⃣ Tables inside a specific room
# ----------------------------------------------------------------------
@staff_required
def room_tables(request, room_id):
    """
    List every Table that belongs to a Room and pre‑fetch the (optional) Order
    together with its Seats, Modifiers and Temperatures.
    """
    room = get_object_or_404(Room, pk=room_id)

    # The reverse accessor from Table → Order is **orders** (see Order.table)
    tables = (
        room.tables.all()
        .prefetch_related(
            models.Prefetch(
                "orders",
                queryset=Order.objects.select_related("opened_by_staff")
                .prefetch_related(
                    "seats__selections__modifiers",
                    "seats__selections__temperatures",
                )
            )
        )
    )

    StaffLog.objects.create(
        staff_id=request.session["staff_id"],
        action=f"viewed tables for room {room.name}",
    )
    return render(request, "orders/room_tables.html", {"room": room, "tables": tables})


# ----------------------------------------------------------------------
# 4️⃣ Consolidated ticket for a whole room (HTML version)
# ----------------------------------------------------------------------
@staff_required
def print_room_ticket(request, room_id):
    room = get_object_or_404(Room, pk=room_id)

    # Grab every *open* order that belongs to this room.
    orders = (
        Order.objects.filter(table__room=room, printed=False)
        .select_related("table")
        .prefetch_related(
            "seats__selections__modifiers",
            "seats__selections__temperatures",
        )
    )

    StaffLog.objects.create(
        staff_id=request.session["staff_id"],
        action=f"printed consolidated ticket for room {room.name}",
    )
    context = {
        "room": room,
        "orders": orders,
        "now": timezone.now(),
    }
    # Render the same template we used for a single‑table ticket,
    # but it loops over *all* orders in the room.
    return render(request, "orders/print_room.html", context)


# ----------------------------------------------------------------------
# 5️⃣ (Optional) PDF version of the consolidated ticket – commented out
# ----------------------------------------------------------------------
# @staff_required
# def print_room_ticket_pdf(request, room_id):
#     from django.template.loader import render_to_string
#     import weasyprint
#
#     room = get_object_or_404(Room, pk=room_id)
#     orders = (
#         Order.objects.filter(table__room=room, printed=False)
#         .select_related("table")
#         .prefetch_related(
#             "seats__selections__modifiers",
#             "seats__selections__temperatures",
#         )
#     )
#     html = render_to_string(
#         "orders/print_room.html",
#         {"room": room, "orders": orders, "now": timezone.now()},
#         request=request,
#     )
#     pdf = weasyprint.HTML(string=html, base_url=request.build_absolute_uri()).write_pdf()
#     response = HttpResponse(pdf, content_type="application/pdf")
#     response["Content-Disposition"] = f'inline; filename="room-{room.id}-ticket.pdf"'
#     return response


# ----------------------------------------------------------------------
# Helper – builds the context dictionary expected by table_view.html
# ----------------------------------------------------------------------
def _build_table_context(request, table: Table, party: Party | None = None) -> dict:
    """
    Returns a dict with everything the template needs.

    `request` is required to read the optional ?new_seat=, ?my_start=,
    ?my_end=, ?active_seat= query‑string parameters.
    """
    order: Order | None = Order.objects.filter(table=table, printed=False).first()
    opened_by = order.opened_by_staff if order else None

    # ------------------------------------------------------------------
    # 1️⃣ Read the optional query‑string parameters
    # ------------------------------------------------------------------
    new_seat_id = request.GET.get("new_seat")
    new_seat_id = int(new_seat_id) if new_seat_id and new_seat_id.isdigit() else None

    active_seat_id = request.GET.get("active_seat")
    active_seat_id = (
        int(active_seat_id) if active_seat_id and active_seat_id.isdigit() else None
    )

    my_start = request.GET.get("my_start")
    my_end = request.GET.get("my_end")
    if my_start and my_end and my_start.isdigit() and my_end.isdigit():
        my_start = int(my_start)
        my_end = int(my_end)
        if my_start > my_end:  # sanity‑swap
            my_start, my_end = my_end, my_start
    else:
        my_start = my_end = None

    # ------------------------------------------------------------------
    # 2️⃣ Retrieve seats (prefetch selections) and apply the slice
    # ------------------------------------------------------------------
    if order:
        all_seats_qs = order.seats.prefetch_related(
            "selections__modifiers", "selections__temperatures"
        )
        all_seats = list(all_seats_qs)

        if my_start is not None and my_end is not None:
            visible_seats = [
                s
                for s in all_seats
                if s.label.isdigit() and my_start <= int(s.label) <= my_end
            ]
        else:
            visible_seats = all_seats

        # Numeric sort – numbers first, then any non‑numeric labels
        def _seat_sort_key(seat: Seat):
            return (0, int(seat.label)) if seat.label.isdigit() else (1, seat.label)

        visible_seats.sort(key=_seat_sort_key)
    else:
        visible_seats = []

    # ------------------------------------------------------------------
    # 3️⃣ Build the menu & modifiers list (unchanged)
    # ------------------------------------------------------------------
    if party:
        menu_items = (
            MenuItem.objects.filter(
                partymenuitem__party=party, partymenuitem__available=True
            )
            .select_related("course")
            .order_by("course__ordering", "name")
        )
    else:
        menu_items = MenuItem.objects.all().select_related("course").order_by(
            "course__ordering", "name"
        )
    modifiers = Modifier.objects.all()

    return {
        "party": party,
        "table": table,
        "order": order,
        "opened_by": opened_by,
        "seats": visible_seats,
        "menu_items": menu_items,
        "modifiers": modifiers,
        "new_seat_id": new_seat_id,
        "active_seat_id": active_seat_id,
        "my_start": my_start,
        "my_end": my_end,
    }


# ----------------------------------------------------------------------
# 1️⃣ Table detail – renders the main UI (templates/orders/table_view.html)
# ----------------------------------------------------------------------
def table_detail(request, table_id):
    """
    GET – show the tablet UI for a specific table.
    """
    table = get_object_or_404(Table, pk=table_id)
    party = table.party  # may be None for legacy tables
    context = _build_table_context(request, table, party)
    context["start_order_form"] = StartOrderForm()
    return render(request, "orders/table_view.html", context)


# ----------------------------------------------------------------------
# 2️⃣ Start a new order (staff‑code version)
# ----------------------------------------------------------------------
@staff_required
def start_order(request, table_id):
    """
    Creates a new Order for the given Table.
    Uses the staff‑code session (StaffMember) instead of request.user.
    """
    table = get_object_or_404(Table, pk=table_id)

    # ------------------------------------------------------------------
    # 1️⃣ Retrieve the StaffMember instance from the session
    # ------------------------------------------------------------------
    staff_id = request.session.get("staff_id")
    if not staff_id:
        messages.error(request, "Staff session lost – please log in again.")
        return redirect("orders:staff_login")
    staff_member = StaffMember.objects.get(pk=staff_id)

    # ------------------------------------------------------------------
    # 2️⃣ Determine the seat range (if the UI supplies my_start / my_end)
    # ------------------------------------------------------------------
    my_start = request.POST.get("my_start")
    my_end = request.POST.get("my_end")
    seat_count = int(request.POST.get("seat_count", 12))  # default fallback

    if my_start is not None and my_end is not None:
        try:
            my_start = int(my_start)
            my_end = int(my_end)
        except ValueError:
            messages.error(request, "Invalid seat range.")
            return redirect('orders:table_detail', table_id=table.id)

    # ------------------------------------------------------------------
    # 3️⃣ Create the Order and the Seats inside an atomic transaction
    # ------------------------------------------------------------------
    with transaction.atomic():
        order = Order.objects.create(
            table=table,
            party=table.party,
            opened_by_staff=staff_member,
            opened_at=timezone.now(),
        )

        seats_to_create = []
        if my_start is not None and my_end is not None:
            for i in range(my_start, my_end + 1):
                seats_to_create.append(
                    Seat(order=order, label=str(i), assigned_to=None)
                )
        else:
            for i in range(1, seat_count + 1):
                seats_to_create.append(
                    Seat(order=order, label=str(i), assigned_to=None)
                )
        Seat.objects.bulk_create(seats_to_create)

    # ------------------------------------------------------------------
    # 4️⃣ Optional audit log + user feedback
    # ------------------------------------------------------------------
    StaffLog.objects.create(
        staff=staff_member,
        action=f"started order #{order.id} on table {table.number} "
        f"with {len(seats_to_create)} seats",
    )
    messages.success(
        request,
        f"Order started on Table {table.number} with {len(seats_to_create)} seats.",
    )
    return redirect('orders:table_detail', table_id=table.id)


# ----------------------------------------------------------------------
# 3️⃣ Join an existing order – add a new seat‑range
# ----------------------------------------------------------------------
@require_POST
def join_order(request, table_id):
    """
    Add a new seat-range to an existing order for the given table.
    Uses the staff-code session (StaffMember) for seat assignment.
    """
    table = get_object_or_404(Table, pk=table_id)

    # Must already be an open order for this table
    order = Order.objects.filter(table=table, printed=False).first()
    if not order:
        messages.info(request, "No order exists yet – please start one first.")
        return redirect(reverse("orders:start_order", args=[table.pk]))

    form = StartOrderForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Invalid range – please correct the values.")
        return redirect(reverse("orders:table_detail", args=[table.pk]))

    my_start = form.cleaned_data.get("my_seat_start")
    my_end = form.cleaned_data.get("my_seat_end")
    seat_count = form.cleaned_data.get("seat_count") or 12

    # Resolve the staff member for assignment
    staff_id = request.session.get("staff_id")
    staff_member = StaffMember.objects.get(pk=staff_id) if staff_id else None

    if my_start is not None and my_end is not None:
        occupied = existing_numeric_labels(order)
        requested = set(range(my_start, my_end + 1))
        overlap = occupied.intersection(requested)
        if overlap:
            overlap_str = ", ".join(str(num) for num in sorted(overlap))
            messages.error(
                request,
                f"The seats {overlap_str} already exist in this order. "
                "Pick a different range.",
            )
            return redirect(
                reverse("orders:table_detail", args=[table.pk])
                + f"?my_start={my_start}&my_end={my_end}"
            )
        seats_to_create = [
            Seat(order=order, label=str(i), assigned_to=staff_member)
            for i in range(my_start, my_end + 1)
        ]
        Seat.objects.bulk_create(seats_to_create)
        created_msg = f"{len(seats_to_create)} seats added (#{my_start}-{my_end})."
    else:
        # No explicit range – create a block of `seat_count` seats
        seats_to_create = [
            Seat(order=order, label=str(i), assigned_to=staff_member)
            for i in range(1, seat_count + 1)
        ]
        # Avoid duplicates if the order already has some of these numbers
        existing = existing_numeric_labels(order)
        seats_to_create = [
            s for s in seats_to_create if int(s.label) not in existing
        ]
        Seat.objects.bulk_create(seats_to_create)
        created_msg = f"{len(seats_to_create)} seats added (no explicit range)."

    messages.success(request, created_msg)

    redirect_url = reverse("orders:table_detail", args=[table.pk])
    if my_start is not None and my_end is not None:
        redirect_url += f"?my_start={my_start}&my_end={my_end}"
    return redirect(redirect_url)


# ----------------------------------------------------------------------
# 4️⃣ Close an order (marks it as printed)
# ----------------------------------------------------------------------
@require_POST
def close_order(request, order_id):
    """
    Mark the order as closed/printed **and delete it**.
    Afterwards redirect to the room view so the staff sees the table as idle.
    """
    order = get_object_or_404(Order, pk=order_id)
    staff_id = request.session.get("staff_id")
    if staff_id:
        StaffLog.objects.create(
            staff_id=staff_id,
            action=f"closed order #{order.id} on table {order.table.number}",
        )
    room_id = order.table.room.id          # keep the room id for the redirect
    order.delete()                         # removes seats, selections, etc.

    messages.info(request, "Order closed.")
    return redirect("orders:room_tables", room_id=room_id)


# ----------------------------------------------------------------------
# 5️⃣ Seats (add / remove)
# ----------------------------------------------------------------------
@require_POST
def add_seat(request: Any, order_id: int) -> Any:
    """
    Add a new seat to an existing order.
    The new seat gets the next numeric label (auto‑increment).
    """
    order = get_object_or_404(Order, pk=order_id)

    existing_labels = order.seats.values_list("label", flat=True)
    numeric_labels = [int(lbl) for lbl in existing_labels if lbl.isdigit()]
    next_number = max(numeric_labels, default=0) + 1
    auto_label = str(next_number)

    new_seat = Seat.objects.create(order=order, label=auto_label)

    messages.success(request, f"Seat #{auto_label} added.")
    return redirect(
        reverse("orders:table_detail", args=[order.table.pk])
        + f"?new_seat={new_seat.id}"
    )


@require_POST
def remove_seat(request, seat_id):
    seat = get_object_or_404(Seat, pk=seat_id)
    table_id = seat.order.table.pk
    seat.delete()
    messages.info(request, f'Seat "{seat.label}" removed.')
    return redirect(reverse("orders:table_detail", args=[table_id]))


# --------------------------------------------------------------
# 1️⃣ Add a selection (menu item + optional modifiers/temperatures)
# --------------------------------------------------------------
@require_POST
def add_selection(request):
    """
    Expected POST keys (matching the HTML form):
        seat_id          - int, required
        item_id          - int, required
        modifier_ids[]   - list of ints (optional)
        temperature_ids[]- list of ints (optional)
        notes            - string (optional)
    """
    seat_id = request.POST.get("seat_id")
    item_id = request.POST.get("item_id")
    notes = request.POST.get("notes", "").strip()
    modifier_ids = request.POST.getlist("modifier_ids")      # may be empty
    temperature_ids = request.POST.getlist("temperature_ids")  # may be empty

    # Basic validation – let Django raise 404 if anything is missing/invalid
    seat = get_object_or_404(Seat, pk=seat_id)
    item = get_object_or_404(MenuItem, pk=item_id)

    # Create (or get) the SeatSelection
    selection, created = SeatSelection.objects.get_or_create(
        seat=seat,
        item=item,
        defaults={"notes": notes},
    )
    # If the selection already existed and we have new notes, append them
    if not created and notes:
        selection.notes = (selection.notes + "\n" + notes).strip()
        selection.save()

    # Attach any modifiers the user selected
    if modifier_ids:
        mods = Modifier.objects.filter(pk__in=modifier_ids)
        selection.modifiers.add(*mods)

    # Attach any temperatures the user selected
    if temperature_ids:
        temps = Temperature.objects.filter(pk__in=temperature_ids)
        selection.temperatures.add(*temps)

    messages.success(
        request,
        f'Updated selection for "{item.name}" on seat "{seat.label}".'
    )

    # Keep the UI focused on the same seat after the redirect
    redirect_url = reverse("orders:table_detail", args=[seat.order.table.pk])
    redirect_url += f"?active_seat={seat.id}"
    return redirect(redirect_url)


# --------------------------------------------------------------
# 2️⃣ Remove a selection
# --------------------------------------------------------------
@require_POST
def remove_selection(request, selection_id):
    """
    Delete a specific SeatSelection.
    """
    selection = get_object_or_404(SeatSelection, pk=selection_id)
    table_id = selection.seat.order.table.pk
    selection.delete()
    messages.info(request, "Selection removed.")
    return redirect(reverse("orders:table_detail", args=[table_id]))


# --------------------------------------------------------------
# 3️⃣ Print a ticket for a single order (HTML version)
# --------------------------------------------------------------
@staff_required
def print_ticket(request, order_id):
    """
    Render a printable HTML ticket for a single order.
    The template `orders/print_room.html` works for a single order as well –
    it simply receives a queryset with one order.
    """
    order = get_object_or_404(Order, pk=order_id)

    # Re‑use the same context structure we use for the room‑wide ticket,
    # but with a single‑element queryset.
    context = {
        "room": order.table.room,          # the room the table belongs to
        "orders": [order],                # a list with just this order
        "now": timezone.now(),
    }

    # Log the print action (optional audit)
    staff_id = request.session.get("staff_id")
    if staff_id:
        StaffLog.objects.create(
            staff_id=staff_id,
            action=f"printed ticket for order #{order.id} (table {order.table.number})",
        )

    return render(request, "orders/print_room.html", context)

# ----------------------------------------------------------------------
# 6️⃣ Move a selection (AJAX)
# ----------------------------------------------------------------------
# orders/views.py
# … (all the imports and other view definitions you already have) …

@require_POST
def move_selection(request):
    """
    AJAX endpoint – moves a SeatSelection to another seat.

    Expected POST data:
        selection_id   – PK of the SeatSelection to move
        target_seat_id – PK of the Seat that should become the new owner

    Returns JSON { "status": "ok" } on success.
    """
    # ------------------------------------------------------------------
    # 1️⃣ Grab the IDs from the request
    # ------------------------------------------------------------------
    sel_id = request.POST.get("selection_id")
    target_seat_id = request.POST.get("target_seat_id")

    # ------------------------------------------------------------------
    # 2️⃣ Basic validation – make sure both IDs are present
    # ------------------------------------------------------------------
    if not sel_id or not target_seat_id:
        return JsonResponse(
            {"status": "error", "message": "Missing selection_id or target_seat_id"},
            status=400,
        )

    # ------------------------------------------------------------------
    # 3️⃣ Fetch the objects (will raise 404 if anything is wrong)
    # ------------------------------------------------------------------
    selection = get_object_or_404(SeatSelection, pk=sel_id)
    target_seat = get_object_or_404(Seat, pk=target_seat_id)

    # ------------------------------------------------------------------
    # 4️⃣ Perform the move – simply re‑assign the foreign key
    # ------------------------------------------------------------------
    selection.seat = target_seat
    selection.save()

    # ------------------------------------------------------------------
    # 5️⃣ Optional audit log (helps you see who moved what)
    # ------------------------------------------------------------------
    staff_id = request.session.get("staff_id")
    if staff_id:
        StaffLog.objects.create(
            staff_id=staff_id,
            action=(
                f"moved selection #{selection.pk} (item {selection.item.name}) "
                f"to seat #{target_seat.label} on table {target_seat.order.table.number}"
            ),
        )

    # ------------------------------------------------------------------
    # 6️⃣ Return a tiny JSON payload the front‑end can interpret
    # ------------------------------------------------------------------
    return JsonResponse({"status": "ok"})