# orders/admin.py
"""
Admin configuration with true three‑level nesting (Order → Seat → SeatSelection)
using django‑nested‑admin.
"""

import csv
import io

from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html

from nested_admin import NestedModelAdmin, NestedStackedInline, NestedTabularInline

from .forms import StaffMemberAdminForm
from .models import (
    Room,
    Table,
    Course,
    MenuItem,
    Temperature,
    Modifier,
    Order,
    Seat,
    SeatSelection,
    OrderLine,
    StaffMember,
    StaffLog,
)

# ----------------------------------------------------------------------
# 1️⃣ StaffMember – lightweight code‑only login
# ----------------------------------------------------------------------
@admin.register(StaffMember)
class StaffMemberAdmin(admin.ModelAdmin):
    form = StaffMemberAdminForm
    list_display = ("name",)
    search_fields = ("name",)


# ----------------------------------------------------------------------
# 2️⃣ Course
# ----------------------------------------------------------------------
@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("name", "ordering")
    ordering = ("ordering",)


# ----------------------------------------------------------------------
# 3️⃣ Room
# ----------------------------------------------------------------------
@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


# ----------------------------------------------------------------------
# 4️⃣ Table
# ----------------------------------------------------------------------
@admin.register(Table)
class TableAdmin(admin.ModelAdmin):
    list_display = ("number", "room")
    list_filter = ("room",)
    search_fields = ("number", "room__name")


# ----------------------------------------------------------------------
# 5️⃣ Modifier and Temperature
# ----------------------------------------------------------------------
@admin.register(Modifier)
class ModifierAdmin(admin.ModelAdmin):
    list_display = ("label", "name")
    search_fields = ("label", "name")


@admin.register(Temperature)
class TemperatureAdmin(admin.ModelAdmin):
    list_display = ("label", "name")
    search_fields = ("label", "name")


# ----------------------------------------------------------------------
# 6️⃣ MenuItem – CSV import (creates Course on‑the‑fly)
# ----------------------------------------------------------------------
@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ("name", "course")
    search_fields = ("name", "course__name")
    filter_horizontal = ("modifiers", "temperatures")
    list_filter = ("course",)
    actions = ["import_csv"]

    def import_csv(self, request, queryset):
        """Expect CSV: name,course_name (header optional)."""
        if "csv_file" not in request.FILES:
            self.message_user(
                request,
                "Attach a CSV file using the file selector below.",
                level=messages.ERROR,
            )
            return

        csv_file = request.FILES["csv_file"]
        decoded = csv_file.read().decode("utf-8")
        reader = csv.reader(io.StringIO(decoded))

        created = updated = 0
        for row in reader:
            if len(row) < 2:
                continue
            name, course_name = row[0].strip(), row[1].strip()
            if not name or not course_name:
                continue

            # Get or create the Course
            course_obj, _ = Course.objects.get_or_create(name=course_name)

            # Create or update the MenuItem
            obj, created_flag = MenuItem.objects.update_or_create(
                name=name, defaults={"course": course_obj}
            )
            if created_flag:
                created += 1
            else:
                updated += 1

        self.message_user(
            request,
            f"CSV processed – {created} new items, {updated} updated.",
            level=messages.SUCCESS,
        )

    import_csv.short_description = "Import menu items (name,course) from CSV"


# ----------------------------------------------------------------------
# 7️⃣ OrderLine – legacy (kept for backward compatibility)
# ----------------------------------------------------------------------
@admin.register(OrderLine)
class OrderLineAdmin(admin.ModelAdmin):
    list_display = ("order", "item", "short_modifiers", "notes")
    list_filter = ("order", "item")
    search_fields = ("order__id", "item__name", "notes")

    def short_modifiers(self, obj):
        return ", ".join(m.label for m in obj.modifiers.all())

    short_modifiers.short_description = "Modifiers"


# ----------------------------------------------------------------------
# 8️⃣ SeatSelection – deepest level (nested inline)
# ----------------------------------------------------------------------
class SeatSelectionInline(NestedTabularInline):
    model = SeatSelection
    extra = 1
    filter_horizontal = ("modifiers", "temperatures")
    verbose_name = "Seat selection"
    verbose_name_plural = "Seat selections"


# ----------------------------------------------------------------------
# 9️⃣ Seat – second‑level inline (child of Order)
# ----------------------------------------------------------------------
class SeatInline(NestedStackedInline):
    model = Seat
    extra = 2
    inlines = [SeatSelectionInline]  # true nesting thanks to django‑nested‑admin
    verbose_name = "Seat"
    verbose_name_plural = "Seats"


# ----------------------------------------------------------------------
# 🔟 Order – top‑level admin, shows Seats (and their selections) inline
# ----------------------------------------------------------------------
@admin.register(Order)
class OrderAdmin(NestedModelAdmin):
    list_display = ("id", "table", "opened_at", "opened_by_staff", "party")
    list_filter = ("opened_at", "party", "opened_by_staff")
    search_fields = ("id", "table__number", "opened_by_staff__name")
    inlines = [SeatInline]

    readonly_fields = ("opened_at", "opened_by_staff")
    fieldsets = (
        (None, {"fields": ("table", "party", "opened_by_staff", "opened_at")}),
    )

    actions = ["mark_as_closed"]

    def mark_as_closed(self, request, queryset):
        """Bulk‑action – mark selected orders as closed/printed."""
        updated = queryset.update(printed=True)
        self.message_user(request, f"{updated} order(s) marked as closed.")
    mark_as_closed.short_description = "Mark selected orders as closed"

    # ------------------------------------------------------------------
    # Helper to colour‑code the printed flag (optional visual aid)
    # ------------------------------------------------------------------
    def print_status(self, obj):
        if obj.printed:
            return format_html("<span style='color:green;'>Printed</span>")
        return format_html("<span style='color:red;'>Not printed</span>")

    print_status.short_description = "Print state"


# ----------------------------------------------------------------------
# 11️⃣ StaffLog – optional audit view (read‑only)
# ----------------------------------------------------------------------
@admin.register(StaffLog)
class StaffLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "staff", "action")
    list_filter = ("staff", "timestamp")
    search_fields = ("staff__name", "action")
    readonly_fields = ("timestamp", "staff", "action")

    def has_add_permission(self, request):
        # Prevent manual creation – logs should only be written by code
        return False

    def has_change_permission(self, request, obj=None):
        # Logs are immutable once created
        return False