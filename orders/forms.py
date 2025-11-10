# orders/forms.py
from django import forms
from django.forms import (
    inlineformset_factory,
    BaseInlineFormSet,
    formset_factory,          # needed for SeatSelectionFormSet
)
from django.core.exceptions import ValidationError
from .models import Order, Seat, SeatSelection, Table, MenuItem, Modifier, StaffMember

class StaffMemberAdminForm(forms.ModelForm):
    """
    Allows the admin to type a plain‑text code.
    The form will hash the code before saving.
    """
    code = forms.CharField(
        max_length=20,
        required=True,
        help_text="Enter the secret personal code for this staff member (will be stored hashed).",
        widget=forms.TextInput(attrs={'autocomplete': 'off'})
    )

    class Meta:
        model = StaffMember
        fields = ('name', 'code')   # we expose only name + raw code

    def save(self, commit=True):
        # Override save to hash the code before persisting
        instance = super().save(commit=False)
        raw_code = self.cleaned_data['code']
        instance.set_code(raw_code)   # uses the model's hashing helper
        if commit:
            instance.save()
        return instance

# ----------------------------------------------------------------------
# ①  StartOrderForm – lets the user decide how many seats to create
#      and optionally assign a range of seats to the current server.
# ----------------------------------------------------------------------
class StartOrderForm(forms.Form):
    """
    Three fields:

        * seat_count      - total number of seats (used only when no range is given)
        * my_seat_start   - first seat number the current server will handle
        * my_seat_end     - last seat number the current server will handle
    """
    seat_count = forms.IntegerField(
        min_value=1,
        required=False,                     # optional – ignored when a range is supplied
        label="Number of seats",
        help_text="How many seats does this table have? (ignored if you set a range)",
        initial=12,
        widget=forms.HiddenInput,
    )
    my_seat_start = forms.IntegerField(
        min_value=1,
        required=False,
        label="My first seat number",
        help_text="First seat number you will handle (optional).",
    )
    my_seat_end = forms.IntegerField(
        min_value=1,
        required=False,
        label="My last seat number",
        help_text="Last seat number you will handle (optional).",
    )

    def clean(self):
        """
        Validation rules:
            * If either start or end is supplied, BOTH must be supplied.
            * start must be ≤ end.
            * end cannot be larger than the total seat count (if seat_count is given).
            * If a valid range is supplied we keep it; otherwise we fall back to seat_count.
        """
        cleaned = super().clean()
        start = cleaned.get("my_seat_start")
        end = cleaned.get("my_seat_end")
        count = cleaned.get("seat_count")

        # 1️⃣ Both‑or‑neither rule
        if (start is not None) ^ (end is not None):
            raise ValidationError(
                "Both “My first seat number” and “My last seat number” must be filled "
                "or both left empty."
            )

        # 2️⃣ If a range is provided, validate it
        if start is not None and end is not None:
            if start > end:
                raise ValidationError(
                    "The first seat number cannot be greater than the last seat number."
                )
            if count is not None and end > count:
                raise ValidationError(
                    "The seat range cannot exceed the total number of seats you entered."
                )
            # Values are already integers; keep them as‑is
            cleaned["my_seat_start"] = start
            cleaned["my_seat_end"] = end

        # Nothing else to do – return the cleaned dict
        return cleaned


# ----------------------------------------------------------------------
# ② OrderForm – only needs the table (the room is implied by the table)
# ----------------------------------------------------------------------
class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ["table"]
        widgets = {
            "table": forms.Select(attrs={"class": "form-select"}),
        }


# ----------------------------------------------------------------------
# ③ SeatFormSet – creates Seat objects linked to the Order
# ----------------------------------------------------------------------
class BaseSeatFormSet(BaseInlineFormSet):
    """Enforce that each seat has a unique label within the order."""
    def clean(self):
        super().clean()
        labels = []
        for form in self.forms:
            if self.can_delete and self._should_delete_form(form):
                continue
            label = form.cleaned_data.get("label")
            if label:
                if label in labels:
                    raise forms.ValidationError(
                        f'Duplicate seat label "{label}". Each seat must be unique.'
                    )
                labels.append(label)


SeatFormSet = inlineformset_factory(
    parent_model=Order,
    model=Seat,
    fields=["label"],
    extra=1,
    can_delete=True,
    formset=BaseSeatFormSet,
)


# ----------------------------------------------------------------------
# ④ SeatSelectionForm – creates selections for a given Seat
# ----------------------------------------------------------------------
class SeatSelectionForm(forms.ModelForm):
    class Meta:
        model = SeatSelection
        fields = ["item", "modifiers", "notes"]
        widgets = {
            "item": forms.Select(attrs={"class": "form-select"}),
            "modifiers": forms.SelectMultiple(attrs={"class": "form-select"}),
            "notes": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Optional note"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Order the menu items by course ordering → course name → item name
        self.fields["item"].queryset = (
            MenuItem.objects.select_related("course")
            .order_by("course__ordering", "course__name", "name")
            .all()
        )


# A regular (non‑inline) formset – we’ll instantiate it manually for each seat
SeatSelectionFormSet = formset_factory(
    SeatSelectionForm,
    extra=1,
    can_delete=True,
)