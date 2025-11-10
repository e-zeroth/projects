# orders/models.py
"""
Data model for the restaurant ordering system.

High-level hierarchy (after the new layer):

Room
 └─ Table (belongs to a Room, optionally linked to a Party)
      └─ Party (event - owns its own menu and a set of Tables)
           └─ Order (one order per table session, optional Party link)
                ├─ Seat (patron at the table, optional assigned server)
                │    └─ SeatSelection (menu item + modifiers + notes)
                └─ OrderLine (legacy line - kept for backward compatibility)

Courses group menu items for printing order tickets.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


# ----------------------------------------------------------------------
# 1️⃣ Core catalogue models (unchanged)
# ----------------------------------------------------------------------
class Course(models.Model):
    """Determines the order in which sections appear on printed tickets."""
    name = models.CharField(max_length=50, unique=True)
    ordering = models.PositiveIntegerField(
        default=0,
        help_text="Lower numbers print first."
    )

    class Meta:
        ordering = ["ordering", "name"]

    def __str__(self):
        return self.name


class Temperature(models.Model):
    """e.g. Rare, Medium‑Rare, Well‑Done, Pink, Blue, etc."""
    label = models.CharField(max_length=30, unique=True)   # short code shown on the card
    name = models.CharField(max_length=80, unique=True)   # full description (shown in order)

    class Meta:
        verbose_name_plural = "Temperatures"

    def __str__(self):
        return self.label


class Modifier(models.Model):
    """Allergy / dietary tags or extra options (e.g., “Gluten‑free”)."""
    label = models.CharField(max_length=80, unique=True)
    name = models.CharField(max_length=80, unique=True)

    def __str__(self):
        return self.label


# ----------------------------------------------------------------------
# 2️⃣ Room – logical area of the venue (Patio, Bar, Main Hall, …)
# ----------------------------------------------------------------------
class Room(models.Model):
    """Logical area of the venue (Patio, Bar, Main Hall, …)."""
    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Room"
        verbose_name_plural = "Rooms"

    def __str__(self):
        return self.name


# ----------------------------------------------------------------------
# 3️⃣ Table – physical table (or bar counter) that lives inside a Room
# ----------------------------------------------------------------------
class Table(models.Model):
    """
    Physical table (or bar counter) that lives inside a Room.

    New: optional FK to a Party – the iPad placed on this table will be
    associated with that Party during the event.
    """
    number = models.PositiveIntegerField()
    room = models.ForeignKey(
        Room,
        related_name="tables",          # makes room.tables work
        on_delete=models.CASCADE,
    )
    # NEW – which event this table belongs to (nullable for legacy data)
    party = models.ForeignKey(
        "Party",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tables",          # Party.tables gives all tables for a party
        help_text="Event that this table participates in.",
    )

    class Meta:
        unique_together = ("number", "room")
        ordering = ["room__name", "number"]

    def __str__(self):
        return f"{self.room.name} – Table {self.number}"


class MenuItem(models.Model):
    """A dish or drink that can be ordered."""
    name = models.CharField(max_length=100, unique=True)
    course = models.ForeignKey(
        Course, on_delete=models.PROTECT, related_name="items"
    )
    # Optional description for the menu card / kitchen ticket
    description = models.TextField(blank=True)

    modifiers = models.ManyToManyField(
        Modifier,
        blank=True,
        related_name="menu_items",
        # through="MenuItemModifier",   # optional through model you may already have
    )
    temperatures = models.ManyToManyField(
        Temperature,
        blank=True,
        related_name="menu_items",
        help_text="Select which temperature / color options are allowed for this dish.",
    )

    def __str__(self):
        return f"{self.name} ({self.course.name})"


# ----------------------------------------------------------------------
# 4️⃣ New layer – Parties (events) and per‑event menus
# ----------------------------------------------------------------------
class Party(models.Model):
    """
    An event (e.g., “John‑Jane Wedding – Hall A”).

    * Owns a collection of Tables (via Table.party).
    * Owns a custom menu (via PartyMenuItem).
    """
    name = models.CharField(max_length=120)
    slug = models.SlugField(
        unique=True,
        help_text="URL‑friendly identifier (e.g. john-wedding-hall-a)."
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="parties_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Auto‑populate slug if missing
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class PartyMenuItem(models.Model):
    """
    Links a MenuItem to a Party.

    * `available` toggles whether the item shows up for that party.
    * `price_override` lets you change the price for a specific event
      without altering the global MenuItem price.
    """
    party = models.ForeignKey(
        Party, on_delete=models.CASCADE, related_name="menu_items"
    )
    menu_item = models.ForeignKey(
        MenuItem, on_delete=models.CASCADE, related_name="party_links"
    )
    available = models.BooleanField(default=True)
    price_override = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="If set, this price replaces the MenuItem.price for the party."
    )

    class Meta:
        unique_together = ("party", "menu_item")
        ordering = ["party", "menu_item__name"]

    def __str__(self):
        return f"{self.menu_item.name} @ {self.party.name} ({'✓' if self.available else '✗'})"


# ----------------------------------------------------------------------
# 5️⃣ Staff – lightweight code‑only login
# ----------------------------------------------------------------------
class StaffMember(models.Model):
    """
    Stores a staff person and a secret *code* (hashed, like a password).
    """
    name = models.CharField(max_length=80)
    code_hash = models.CharField(max_length=128, editable=False)

    class Meta:
        verbose_name = "Staff Member"
        verbose_name_plural = "Staff Members"

    def __str__(self):
        return self.name

    # ------------------------------------------------------------------
    # Helpers – set / verify the secret code
    # ------------------------------------------------------------------
    def set_code(self, raw_code: str) -> None:
        """Hash and store a new secret code."""
        self.code_hash = make_password(raw_code.strip())
        self.save(update_fields=["code_hash"])

    def check_code(self, raw_code: str) -> bool:
        """True if the supplied code matches the stored hash."""
        return check_password(raw_code.strip(), self.code_hash)


# ----------------------------------------------------------------------
# 6️⃣ Simple audit log – who did what and when
# ----------------------------------------------------------------------
class StaffLog(models.Model):
    staff = models.ForeignKey(StaffMember, on_delete=models.CASCADE)
    action = models.CharField(max_length=120)   # e.g. "opened room dashboard"
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M} – {self.staff.name}: {self.action}"


# ----------------------------------------------------------------------
# 7️⃣ Ordering workflow models (updated for staff login)
# ----------------------------------------------------------------------
class Order(models.Model):
    """
    One order per table session.
    After the party finishes, `party` will be filled; for historic data it may stay NULL.
    """
    table = models.ForeignKey('Table', on_delete=models.PROTECT, related_name='orders')
    party = models.ForeignKey('Party', on_delete=models.SET_NULL, null=True, blank=True)

    # Staff member who opened the order (replaces the old `created_by` User FK)
    opened_by_staff = models.ForeignKey(
        StaffMember,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        verbose_name='Opened by staff',
    )
    opened_at = models.DateTimeField(default=timezone.now, editable=False)

    printed = models.BooleanField(default=False)   # Sent to kitchen?
    
    class Meta:
        ordering = ['-opened_at']   # newest first

    def __str__(self):
        return f"Order #{self.pk} – {self.table}"


class Seat(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='seats')
    label = models.CharField(max_length=10)          # e.g. "1", "2", …
    # Which staff member (server) is responsible for this seat?
    assigned_to = models.ForeignKey(
        StaffMember,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='seats',
        verbose_name='Assigned to staff',
    )

    class Meta:
        unique_together = ("order", "label")
        ordering = ["order", "label"]

    def __str__(self):
        return f"{self.label or 'Seat'} (Table {self.order.table.number})"


class SeatSelection(models.Model):
    """
    A line item on a seat’s cart: a MenuItem plus any chosen Modifiers
    and optional free‑form notes.
    """
    seat = models.ForeignKey(Seat, related_name="selections", on_delete=models.CASCADE)
    item = models.ForeignKey(MenuItem, on_delete=models.PROTECT, related_name="seat_selections")
    notes = models.CharField(max_length=200, blank=True)
    modifiers = models.ManyToManyField(Modifier, blank=True, related_name='selections')
    temperatures = models.ManyToManyField(Temperature, blank=True, related_name='selections')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        mods = ", ".join(m.label for m in self.modifiers.all())
        base = f"{self.item.name}"
        if mods:
            base += f" [{mods}]"
        if self.notes:
            base += f" ({self.notes})"
        return base


# ----------------------------------------------------------------------
# 8️⃣ Legacy model – kept for backward compatibility only
# ----------------------------------------------------------------------
class OrderLine(models.Model):
    """
    Older representation of an order line (used only if you still need it).
    New code should prefer SeatSelection.
    """
    order = models.ForeignKey(Order, related_name="lines", on_delete=models.CASCADE)
    item = models.ForeignKey(MenuItem, on_delete=models.PROTECT, related_name="order_lines")
    notes = models.CharField(max_length=200, blank=True)
    modifiers = models.ManyToManyField(Modifier, blank=True)

    def __str__(self):
        mods = ", ".join(m.label for m in self.modifiers.all())
        parts = [self.item.name]
        if mods:
            parts.append(f"[{mods}]")
        if self.notes:
            parts.append(f"({self.notes})")
        return " ".join(parts)


# ----------------------------------------------------------------------
# 9️⃣ Type‑checking hint for the reverse manager (optional but nice)
# ----------------------------------------------------------------------
# if TYPE_CHECKING:   # only evaluated by static type checkers
#     from .seat import Seat   # forward reference to avoid circular import
# Order.seats: Manager["Seat"]  # noqa: F821  (ignore undefined name at runtime)